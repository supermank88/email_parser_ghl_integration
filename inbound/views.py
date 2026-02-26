"""
SendGrid Inbound Parse webhook receiver.

SendGrid posts to this URL with multipart/form-data when an email is received.
See: https://docs.sendgrid.com/for-developers/parsing-email/setting-up-the-inbound-parse-webhook
"""

import email as email_module
import json
import logging
import re
from datetime import datetime
from decimal import Decimal
from email import policy
from pathlib import Path

from django.conf import settings

from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from .pdf_nda import fill_nda_pdf
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.clickjacking import xframe_options_sameorigin

from .models import InboundEmail
from .parsing import parse_email_with_deepseek
from .ghl import sync_contact_to_ghl, upload_nda_to_ghl_media

logger = logging.getLogger(__name__)

# SendGrid Inbound Parse form field names
FIELDS = (
    'from', 'to', 'cc', 'subject', 'text', 'html',
    'sender_ip', 'envelope', 'attachments', 'attachment-info',
    'headers', 'charsets', 'SPF', 'dkim', 'spam_report', 'spam_score',
)


@csrf_exempt
@require_http_methods(['POST'])
def sendgrid_inbound(request):
    """
    Receive inbound email webhook from SendGrid.

    Supports:
    - Parsed form: text, html, from, to, subject (POST).
    - Raw in POST field: full MIME in the "email" field.
    - Send Raw: full MIME as request.body when Content-Type is not multipart.
    - Body in FILES: text/html or raw MIME in file parts.

    Use DATA_UPLOAD_MAX_MEMORY_SIZE large enough for big emails (e.g. 25 MB).
    """
    try:
        payload = {}
        for key in FIELDS:
            value = request.POST.get(key)
            if value is not None:
                payload[key] = value
        # Capture any other POST keys (e.g. alternate body field names)
        for key in request.POST:
            if key not in payload:
                payload[key] = request.POST.get(key)
        # Ensure we capture body: SendGrid uses 'text' and 'html'; fallback to 'body' or 'email'
        if not payload.get('text') and payload.get('body'):
            payload['text'] = payload['body']
        if not payload.get('html') and payload.get('html_body'):
            payload['html'] = payload['html_body']
        # SendGrid can send the full message in the 'email' POST field (raw MIME string)
        if (not payload.get('text') and not payload.get('html')) and payload.get('email'):
            email_raw = payload['email']
            if isinstance(email_raw, bytes):
                email_raw = email_raw.decode('utf-8', errors='replace')
            email_raw = email_raw.strip()
            if email_raw.lstrip().startswith(('From ', 'Received:', 'Content-Type:', 'Message-ID:', 'MIME-Version:')):
                try:
                    msg = email_module.message_from_string(email_raw, policy=policy.default)
                    for part in msg.walk():
                        if part.get_content_maintype() == 'multipart':
                            continue
                        ct_part = (part.get_content_type() or '').lower()
                        payload_part = part.get_payload(decode=True)
                        if payload_part:
                            try:
                                payload_str = payload_part.decode('utf-8', errors='replace')
                            except Exception:
                                payload_str = payload_part.decode('latin-1', errors='replace')
                            if ct_part == 'text/plain':
                                payload['text'] = payload_str
                            elif ct_part == 'text/html':
                                payload['html'] = payload_str
                    if not payload.get('from') and msg.get('from'):
                        payload['from'] = msg.get('from')
                    if not payload.get('to') and msg.get('to'):
                        payload['to'] = msg.get('to')
                    if not payload.get('subject') and msg.get('subject'):
                        payload['subject'] = msg.get('subject')
                    mid = msg.get('Message-ID', '') or ''
                    if isinstance(mid, str):
                        payload['message_id'] = mid.strip()[:512]
                    logger.info('Extracted body from POST email field (raw MIME)')
                except Exception as e:
                    logger.debug('Failed to parse POST email as MIME: %s', e)
                    payload['text'] = email_raw
            else:
                payload['text'] = email_raw

        # Collect attachment count and file objects
        num_attachments = request.POST.get('attachments', '0')
        try:
            num_attachments = int(num_attachments)
        except (TypeError, ValueError):
            num_attachments = 0

        attachment_keys = {f'attachment{i}' for i in range(1, num_attachments + 1)}
        attachments = []

        for file_key, f in request.FILES.items():
            try:
                raw = b''.join(chunk for chunk in f.chunks())
            except Exception:
                raw = b''
            if file_key in attachment_keys:
                attachments.append({
                    'name': f.name,
                    'size': f.size,
                    'content_type': f.content_type,
                })
                continue
            if not raw.strip():
                continue
            ct = (f.content_type or '').lower()
            # Raw MIME (SendGrid "POST the raw, full MIME message" mode)
            if ct in ('message/rfc822', 'text/rfc822') or raw.lstrip().startswith((b'From ', b'Received:', b'Content-Type:', b'Message-ID:')):
                try:
                    msg = email_module.message_from_bytes(raw, policy=policy.default)
                    for part in msg.walk():
                        if part.get_content_maintype() == 'multipart':
                            continue
                        ct_part = (part.get_content_type() or '').lower()
                        payload_part = part.get_payload(decode=True)
                        if payload_part:
                            try:
                                payload_str = payload_part.decode('utf-8', errors='replace')
                            except Exception:
                                payload_str = payload_part.decode('latin-1', errors='replace')
                            if ct_part == 'text/plain' and not payload.get('text'):
                                payload['text'] = payload_str
                            elif ct_part == 'text/html' and not payload.get('html'):
                                payload['html'] = payload_str
                    if not payload.get('from') and msg.get('from'):
                        payload['from'] = msg.get('from')
                    if not payload.get('to') and msg.get('to'):
                        payload['to'] = msg.get('to')
                    if not payload.get('subject') and msg.get('subject'):
                        payload['subject'] = msg.get('subject')
                    mid = msg.get('Message-ID', '') or ''
                    if isinstance(mid, str):
                        payload['message_id'] = mid.strip()[:512]
                    logger.info('Extracted body from raw MIME file %s', file_key)
                except Exception as e:
                    logger.debug('Failed to parse as raw MIME: %s', e)
                continue
            # Plain file part (body sent as file)
            try:
                content = raw.decode('utf-8', errors='replace')
            except Exception:
                content = raw.decode('latin-1', errors='replace')
            if not content.strip():
                continue
            if file_key.lower() in ('text', 'plain', 'body') or 'text/plain' in ct:
                if not payload.get('text'):
                    payload['text'] = content
            elif file_key.lower() in ('html', 'html_body') or 'text/html' in ct:
                if not payload.get('html'):
                    payload['html'] = content
            elif ct.startswith('text/') or not ct:
                if not payload.get('text') and 'html' not in ct:
                    payload['text'] = content
                elif not payload.get('html') and 'html' in ct:
                    payload['html'] = content

        payload['attachment_list'] = attachments

        has_body = bool(payload.get('text') or payload.get('html'))

        # When SendGrid "Send Raw" is enabled, the raw MIME may be the entire request.body (not in POST)
        if not has_body and getattr(request, 'body', b''):
            raw_body = request.body
            if isinstance(raw_body, bytes) and len(raw_body) > 0:
                # Only treat as raw MIME if it looks like an email (avoid parsing multipart form as MIME)
                if raw_body.lstrip().startswith((b'From ', b'Received:', b'Content-Type:', b'Message-ID:', b'MIME-Version:', b'Return-Path:')):
                    try:
                        msg = email_module.message_from_bytes(raw_body, policy=policy.default)
                        for part in msg.walk():
                            if part.get_content_maintype() == 'multipart':
                                continue
                            ct_part = (part.get_content_type() or '').lower()
                            payload_part = part.get_payload(decode=True)
                            if payload_part:
                                try:
                                    payload_str = payload_part.decode('utf-8', errors='replace')
                                except Exception:
                                    payload_str = payload_part.decode('latin-1', errors='replace')
                                if ct_part == 'text/plain':
                                    payload['text'] = payload_str
                                elif ct_part == 'text/html':
                                    payload['html'] = payload_str
                        if not payload.get('from') and msg.get('from'):
                            payload['from'] = msg.get('from')
                        if not payload.get('to') and msg.get('to'):
                            payload['to'] = msg.get('to')
                        if not payload.get('subject') and msg.get('subject'):
                            payload['subject'] = msg.get('subject')
                        mid = msg.get('Message-ID', '') or ''
                        if isinstance(mid, str):
                            payload['message_id'] = mid.strip()[:512]
                        has_body = bool(payload.get('text') or payload.get('html'))
                        if has_body:
                            logger.info('Extracted body from request.body (Send Raw)')
                    except Exception as e:
                        logger.debug('Failed to parse request.body as MIME: %s', e)

        logger.info(
            'Inbound email received from=%s to=%s subject=%s has_body=%s post_keys=%s file_keys=%s',
            payload.get('from'),
            payload.get('to'),
            payload.get('subject'),
            has_body,
            list(payload.keys()),
            list(request.FILES.keys()),
        )
        if not has_body:
            logger.warning(
                'No text/html in webhook. POST keys: %s; FILES keys: %s; body_len=%s. '
                'SendGrid: use parsed fields (text/html) or send raw MIME in POST "email" or as request.body; ensure DATA_UPLOAD_MAX_MEMORY_SIZE is large enough.',
                list(request.POST.keys()),
                list(request.FILES.keys()),
                len(getattr(request, 'body', b'') or b''),
            )

        # Process the email here (e.g. save to DB, trigger GHL automation).
        # For now we just log and return 200 so SendGrid does not retry.
        process_inbound_email(payload, request)

        return HttpResponse(status=200)
    except Exception as e:
        logger.exception('Error processing SendGrid inbound webhook: %s', e)
        return HttpResponse(status=500)


def _extract_message_id(headers_str):
    """Extract Message-ID from raw headers string (e.g. 'Message-ID: <abc@example.com>')."""
    if not headers_str or not isinstance(headers_str, str):
        return ''
    match = re.search(r'Message-ID:\s*<([^>]+)>', headers_str, re.IGNORECASE | re.DOTALL)
    return (match.group(1).strip()[:512]) if match else ''


def process_inbound_email(payload, request):
    """
    Save inbound email to database so it can be displayed.
    """
    envelope = payload.get('envelope') or '{}'
    if isinstance(envelope, str):
        try:
            envelope = json.loads(envelope)
        except (json.JSONDecodeError, TypeError):
            envelope = {}

    # Normalize body: SendGrid uses 'text'/'html'; some configs use 'body' or different case
    text_body = (payload.get('text') or payload.get('body') or '').strip()
    if not text_body:
        for k, v in payload.items():
            if v and isinstance(v, str) and k.lower() in ('text', 'plain', 'body'):
                text_body = v.strip()
                break
    html_body = (payload.get('html') or '').strip()
    if not html_body:
        for k, v in payload.items():
            if v and isinstance(v, str) and k.lower() in ('html', 'html_body'):
                html_body = v.strip()
                break

    message_id = ((payload.get('message_id') or _extract_message_id(payload.get('headers', ''))) or '').strip()[:512]

    email = InboundEmail.objects.create(
        from_address=payload.get('from') or '',
        to_address=payload.get('to') or '',
        cc=payload.get('cc') or '',
        subject=payload.get('subject') or '',
        text_body=text_body,
        html_body=html_body,
        envelope=envelope,
        attachment_info=payload.get('attachment_list', []),
        original_email_message_id=message_id,
    )
    try:
        from django.utils import timezone
        parsed = parse_email_with_deepseek(email)
        if parsed:
            listing_id = (parsed.get('listing_id') or '').strip()
            listing_name = (parsed.get('listing_name') or '').strip()
            lead_email = (parsed.get('email') or '').strip()
            phone = (parsed.get('phone') or '').strip()
            has_lead_data = bool(listing_id or listing_name or lead_email or phone)
            if not has_lead_data:
                logger.info(
                    'Skipping lead save and GHL: no listing_id, listing_name, email, or phone for inbound email id=%s',
                    email.pk,
                )
            else:
                email.email_title = (email.subject or '')[:512]
                email.lead_source = (parsed.get('lead_source') or '')[:128]
                email.listing_id = listing_id[:255]
                email.listing_name = listing_name[:512]
                lp = parsed.get('listing_profit')
                if lp is not None and lp != '':
                    try:
                        email.listing_profit = Decimal(str(lp))
                    except (TypeError, ValueError):
                        email.listing_profit = None
                else:
                    email.listing_profit = None
                email.name = (parsed.get('name') or '')[:255]
                email.email = lead_email[:254]
                email.phone = phone[:64]
                email.purchase_timeframe = (parsed.get('purchase_timeframe') or '')[:255]
                email.amount_to_invest = (parsed.get('amount_to_invest') or '')[:255]
                email.lead_message = (parsed.get('lead_message') or '')[:65535]
                email.ref_id = (parsed.get('ref_id') or '')[:128]
                email.raw_parsed = parsed.get('_raw_parsed', {})
                email.parsed_at = timezone.now()
                email.save(update_fields=[
                    'email_title', 'lead_source', 'listing_id', 'listing_name', 'listing_profit',
                    'name', 'email', 'phone', 'purchase_timeframe', 'amount_to_invest',
                    'lead_message', 'ref_id', 'raw_parsed', 'parsed_at',
                ])
                # Sync to GoHighLevel only when we have lead data (requires listing_id + phone + lead_source)
                try:
                    logger.info(
                        'Attempting GHL sync for email id=%s (listing_id=%r, phone=%r, lead_source=%r)',
                        email.pk, email.listing_id, email.phone, email.lead_source,
                    )
                    ghl_id = sync_contact_to_ghl(email)
                    if ghl_id:
                        email.ghl_contact_id = ghl_id[:64]
                        email.save(update_fields=['ghl_contact_id'])
                except Exception as ghl_err:
                    logger.exception('GHL sync failed for email id=%s: %s', email.pk, ghl_err)
    except Exception as e:
        logger.exception('DeepSeek parsing failed for email id=%s: %s', email.pk, e)


def email_list(request):
    """Display list of received emails."""
    emails = InboundEmail.objects.all()[:100]
    return render(request, 'inbound/email_list.html', {'emails': emails})


def email_detail(request, pk):
    """Display a single received email."""
    email = get_object_or_404(InboundEmail, pk=pk)
    return render(request, 'inbound/email_detail.html', {'email': email})


def nda_contacts_list(request):
    """
    List all available NDA pages: contacts that have ghl_contact_id, listing_id, and phone.
    One entry per (contact_id, listing_id); most recent email used for listing_name, created, name.
    """
    emails = InboundEmail.objects.filter(
        ghl_contact_id__gt='',
        listing_id__gt='',
        phone__gt='',
    ).order_by('-received_at')
    seen = set()
    nda_entries = []
    for e in emails:
        key = (e.ghl_contact_id, e.listing_id)
        if key in seen:
            continue
        seen.add(key)
        nda_entries.append({
            'contact_id': e.ghl_contact_id,
            'listing_id': e.listing_id,
            'listing_name': e.listing_name or '',
            'created': e.received_at.strftime('%Y-%m-%d') if e.received_at else '',
            'name': e.name or '',
            'phone': e.phone or '',
            'email': e.email or '',
        })
    return render(request, 'inbound/nda_contacts.html', {'nda_entries': nda_entries})


def _nda_pdf_response(contact_id, request):
    """Build filled PDF bytes from contact and request GET params."""
    def _get(key, default=''):
        return request.GET.get(key, default) or default
    contact = InboundEmail.objects.filter(ghl_contact_id=contact_id).order_by('-received_at').first()
    extra = (contact.raw_parsed or {}) if contact else {}
    return fill_nda_pdf(
        contact_id=contact_id,
        listing_id=(contact.listing_id if contact else '') or _get('listing_id'),
        listing_name=(contact.listing_name if contact else '') or _get('listing_name'),
        name=(contact.name if contact else '') or _get('name'),
        email=(contact.email if contact else '') or _get('email'),
        phone=(contact.phone if contact else '') or _get('phone'),
        ref_id=(contact.ref_id if contact else '') or _get('ref_id'),
        street_address=extra.get('street_address', '') or _get('street_address'),
        city=extra.get('city', '') or _get('city'),
        state=extra.get('state', '') or _get('state'),
        zip_code=extra.get('zip', '') or _get('zip_code'),
        signature=extra.get('signature', '') or _get('signature'),
        will_manage=extra.get('will_manage', '') or _get('will_manage'),
        other_deciders=extra.get('other_deciders', '') or _get('other_deciders'),
        industry_experience=extra.get('industry_experience', '') or _get('industry_experience'),
        timeframe=(contact.purchase_timeframe if contact else '') or _get('purchase_timeframe'),
        liquid_assets=extra.get('liquid_assets', '') or _get('liquid_assets'),
        real_estate=extra.get('real_estate', '') or _get('real_estate'),
        retirement_401k=extra.get('retirement_401k', '') or _get('retirement_401k'),
        funds_for_business=(contact.amount_to_invest if contact else '') or _get('funds_for_business'),
        partner_name=(contact.lead_message if contact else '') or _get('partner_name'),
        using=extra.get('using', '') or _get('using'),
        govt_affiliation=extra.get('govt_affiliation', '') or _get('govt_affiliation'),
        govt_explain=extra.get('govt_explain', '') or _get('govt_explain'),
    )


def _save_signed_nda_to_static(contact_id, contact):
    """
    Generate filled NDA PDF from contact and save to inbound/static/inbound/nda_signed/.
    Returns the saved file path (relative) or None on failure.
    """
    extra = (contact.raw_parsed or {}) if contact else {}
    try:
        pdf_bytes = fill_nda_pdf(
            contact_id=contact_id,
            listing_id=(contact.listing_id if contact else '') or '',
            listing_name=(contact.listing_name if contact else '') or '',
            name=(contact.name if contact else '') or '',
            email=(contact.email if contact else '') or '',
            phone=(contact.phone if contact else '') or '',
            ref_id=(contact.ref_id if contact else '') or '',
            street_address=extra.get('street_address', ''),
            city=extra.get('city', ''),
            state=extra.get('state', ''),
            zip_code=extra.get('zip', ''),
            signature=extra.get('signature', ''),
            will_manage=extra.get('will_manage', ''),
            other_deciders=extra.get('other_deciders', ''),
            industry_experience=extra.get('industry_experience', ''),
            timeframe=(contact.purchase_timeframe if contact else '') or '',
            liquid_assets=extra.get('liquid_assets', ''),
            real_estate=extra.get('real_estate', ''),
            retirement_401k=extra.get('retirement_401k', ''),
            funds_for_business=extra.get('funds_for_business', '') or (contact.amount_to_invest if contact else '') or '',
            partner_name=(contact.lead_message if contact else '') or '',
            using=extra.get('using', ''),
            govt_affiliation=extra.get('govt_affiliation', ''),
            govt_explain=extra.get('govt_explain', ''),
        )
    except FileNotFoundError:
        logger.warning("NDA template not found; skipping save to static.")
        return None
    except Exception as e:
        logger.exception("Failed to generate NDA PDF for save: %s", e)
        return None

    save_dir = Path(settings.BASE_DIR) / "inbound" / "static" / "inbound" / "nda_signed"
    save_dir.mkdir(parents=True, exist_ok=True)
    safe_id = re.sub(r'[^\w\-]', '_', str(contact_id))[:80]
    listing = re.sub(r'[^\w\-]', '_', (contact.listing_id or contact.listing_name or '')[:50])
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    name = "nda_signed" if not listing else f"nda_signed_{listing}"
    filename = f"{name}_{safe_id}_{ts}.pdf"
    filepath = save_dir / filename
    try:
        filepath.write_bytes(pdf_bytes)
        logger.info("Saved signed NDA to %s", filepath)
        # Upload to GHL Media Storage / Signed_NDA folder
        try:
            upload_nda_to_ghl_media(str(filepath), filename, contact_id, contact)
        except Exception as upload_err:
            logger.exception("GHL media upload failed (local save succeeded): %s", upload_err)
        return f"inbound/nda_signed/{filename}"
    except OSError as e:
        logger.exception("Failed to write signed NDA to %s: %s", filepath, e)
        return None


def nda_page(request, contact_id):
    """
    Main NDA URL: HTML viewer with embedded PDF and footer bar (Requirements left + Next Req).
    """
    contact = InboundEmail.objects.filter(ghl_contact_id=contact_id).order_by('-received_at').first()
    context = _nda_form_context(contact_id, contact)
    if not contact and request.method == 'GET':
        context['listing_id'] = request.GET.get('listing_id', '') or context.get('listing_id', '')
        context['listing_name'] = request.GET.get('listing_name', '') or context.get('listing_name', '')
    qs = request.GET.urlencode()
    # Use relative URL for PDF so iframe loads from same origin (fixes port-forward/tunnel)
    context['pdf_url'] = reverse('inbound:nda_pdf', kwargs={'contact_id': contact_id}) + ('?' + qs if qs else '')
    context['save_url'] = reverse('inbound:nda_save', kwargs={'contact_id': contact_id})
    return render(request, 'inbound/nda_viewer.html', context)


@xframe_options_sameorigin
def nda_pdf_stream(request, contact_id):
    """Return raw PDF bytes for embedding in viewer iframe."""
    try:
        pdf_bytes = _nda_pdf_response(contact_id, request)
    except FileNotFoundError:
        return HttpResponse('NDA template not found.', status=404)
    resp = HttpResponse(pdf_bytes, content_type='application/pdf')
    resp['Content-Disposition'] = 'inline; filename="NDA.pdf"'
    return resp


def nda_save(request, contact_id):
    """POST: save fillable field values. Accepts application/json (from PDF.js form) or form data."""
    if request.method != 'POST':
        return redirect('inbound:nda_page', contact_id=contact_id)

    if request.content_type and 'application/json' in request.content_type:
        try:
            data = json.loads(request.body.decode('utf-8'))
        except (ValueError, UnicodeDecodeError):
            return JsonResponse({'ok': False, 'error': 'Invalid JSON'}, status=400)
        def get(key, alt=None):
            v = data.get(key) or (data.get(alt) if alt else None)
            if v is None:
                return ''
            return (v.strip() if isinstance(v, str) else str(v).strip())
        contact = InboundEmail.objects.filter(ghl_contact_id=contact_id).order_by('-received_at').first()
        contact = contact or InboundEmail(
            ghl_contact_id=contact_id,
            from_address=get('email') or 'nda@local',
            subject='NDA',
        )
        for key in (
            'ref_id', 'listing_id', 'listing_name', 'name', 'email', 'phone',
            'purchase_timeframe', 'amount_to_invest', 'lead_message',
        ):
            if key in data:
                setattr(contact, key, get(key))
        if 'partner_name' in data:
            contact.lead_message = get('partner_name')
        if 'cell' in data and 'phone' not in data:
            contact.phone = get('cell')
        extra = contact.raw_parsed or {}
        extra_keys = (
            'signature', 'street_address', 'city', 'state', 'zip',
            'will_manage', 'other_deciders', 'industry_experience', 'govt_affiliation', 'govt_explain',
            'liquid_assets', 'real_estate', 'retirement_401k', 'funds_for_business', 'using',
        )
        for key in extra_keys:
            if key in data:
                extra[key] = get(key)
        if 'timeframe' in data and 'purchase_timeframe' not in data:
            contact.purchase_timeframe = get('timeframe')
        contact.raw_parsed = extra
        contact.save()
        _save_signed_nda_to_static(contact_id, contact)
        return JsonResponse({'ok': True, 'received_keys': list(data.keys())})

    # Form POST (fallback)
    contact = InboundEmail.objects.filter(ghl_contact_id=contact_id).order_by('-received_at').first()
    contact = contact or InboundEmail(
        ghl_contact_id=contact_id,
        from_address=request.POST.get('email', '') or 'nda@local',
        subject='NDA',
    )
    for key in (
        'ref_id', 'listing_id', 'listing_name', 'name', 'email', 'phone',
        'purchase_timeframe', 'amount_to_invest', 'lead_message',
    ):
        if key in request.POST:
            setattr(contact, key, request.POST.get(key, '').strip())
    if 'partner_name' in request.POST:
        contact.lead_message = request.POST.get('partner_name', '').strip()
    extra = contact.raw_parsed or {}
    extra_keys = (
        'signature', 'street_address', 'city', 'state', 'zip',
        'will_manage', 'other_deciders', 'industry_experience', 'govt_affiliation', 'govt_explain',
        'liquid_assets', 'real_estate', 'retirement_401k', 'funds_for_business', 'using',
    )
    for key in extra_keys:
        if key in request.POST:
            extra[key] = request.POST.get(key, '').strip()
    if 'timeframe' in request.POST and 'purchase_timeframe' not in request.POST:
        contact.purchase_timeframe = request.POST.get('timeframe', '').strip()
    contact.raw_parsed = extra
    contact.save()
    _save_signed_nda_to_static(contact_id, contact)
    url = reverse('inbound:nda_page', kwargs={'contact_id': contact_id})
    return redirect(url + '?saved=1')


# Required NDA fields for "Requirements left" count (empty = 1 requirement)
NDA_REQUIRED_FIELDS = ('name', 'email', 'phone', 'ref_id', 'listing_id', 'listing_name', 'signature')


def _nda_form_context(contact_id, contact):
    """Build context for NDA form page from contact (or empty)."""
    if not contact:
        return {
            'contact_id': contact_id,
            'contact': None,
            'ref_id': '',
            'listing_id': '',
            'listing_name': '',
            'name': '',
            'email': '',
            'phone': '',
            'signature': '',
            'street_address': '',
            'city': '',
            'state': '',
            'zip': '',
            'purchase_timeframe': '',
            'amount_to_invest': '',
            'lead_message': '',
            'will_manage': '',
            'other_deciders': '',
            'industry_experience': '',
            'govt_affiliation': '',
            'govt_explain': '',
            'requirements_count': len(NDA_REQUIRED_FIELDS),
        }
    extra = contact.raw_parsed or {}
    data = {
        'contact_id': contact_id,
        'contact': contact,
        'ref_id': contact.ref_id or '',
        'listing_id': contact.listing_id or '',
        'listing_name': contact.listing_name or '',
        'name': contact.name or '',
        'email': contact.email or '',
        'phone': contact.phone or '',
        'signature': extra.get('signature', ''),
        'street_address': extra.get('street_address', ''),
        'city': extra.get('city', ''),
        'state': extra.get('state', ''),
        'zip': extra.get('zip', ''),
        'purchase_timeframe': contact.purchase_timeframe or '',
        'amount_to_invest': contact.amount_to_invest or '',
        'lead_message': contact.lead_message or '',
        'will_manage': extra.get('will_manage', ''),
        'other_deciders': extra.get('other_deciders', ''),
        'industry_experience': extra.get('industry_experience', ''),
        'govt_affiliation': extra.get('govt_affiliation', ''),
        'govt_explain': extra.get('govt_explain', ''),
    }
    # Count how many required fields are still empty
    count = 0
    for key in NDA_REQUIRED_FIELDS:
        if not (data.get(key) or '').strip():
            count += 1
    data['requirements_count'] = count
    return data


