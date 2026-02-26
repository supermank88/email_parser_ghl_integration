"""
Parse inbound email content using DeepSeek API to extract structured fields.
API key is read from DEEPSEEK_API_KEY in environment (e.g. from .env).
"""

import json
import logging
import os
import re

from django.conf import settings

logger = logging.getLogger(__name__)

# Field keys we expect in the JSON response from DeepSeek
PARSED_KEYS = (
    'lead_source', 'listing_id', 'listing_name', 'listing_profit',
    'name', 'email', 'phone', 'purchase_timeframe',
    'amount_to_invest', 'lead_message', 'ref_id',
)

SYSTEM_PROMPT = """You are an assistant that extracts structured information from business-for-sale lead emails (e.g. BizBuySell, TangentBrokerage, BusinessesforSale.com).

The LEAD is the person interested in buying the business (the inquiry). The email may be forwarded: the "From" header is the sender (e.g. forwarder), NOT necessarily the lead.

IMPORTANT: Extract the lead's name and email from the BODY when present (e.g. "Name: Test Test", "Email: test123@gmail.com", "Contact Name:", "Lead Name:"). Do NOT use the From header for name/email when the body contains explicit lead fields. Only use From/Reply-To for name or email when the body does not contain them.

Given the email headers (From, Reply-To, Subject), body text, and structured lines like "Name:", "Email:", "Phone:", "Lead For:", "Message:", "Amount to Invest:", "Purchase Timeframe:", "Your Ref ID#:", extract the following into a JSON object.

Output a JSON object with exactly these keys (use empty string "" if not found; use null for listing_profit if not found):
- lead_source: one of "BizBuySell", "TangentBrokerage.com", "BusinessesforSale.com" (infer from From address or domain, e.g. leads@bizbuysell.com -> BizBuySell)
- listing_id: listing or reference number (e.g. "2344916" from "Listing# 2344916")
- listing_name: the full listing name / "Lead For" line (e.g. "$539,384 Profit; 2 new large revenue streams w/recent FDA approval!")
- listing_profit: numeric profit only, no currency (e.g. 539384 from "$539,384 Profit"), or null if not found
- name: full name of the LEAD (person inquiring). Prefer value from body "Name:" or similar; do not use the From header sender name when body has a different name.
- email: email of the LEAD. Prefer value from body "Email:" or similar; do not use From address when body has a different lead email.
- phone: phone number of the lead (from body "Phone:" or similar)
- purchase_timeframe: e.g. "3 to 6 Months", "ASAP"
- amount_to_invest: e.g. "Not disclosed", "$500k", or exact text from email
- lead_message: the full message body / inquiry text (the "Message:" section or main paragraph)
- ref_id: value after "Your Ref ID#:" or similar (e.g. "xray")

Return only valid JSON, no other text."""


def _get_text_content(email):
    """Plain text content for the model (prefer text, fallback strip html)."""
    if email.text_body and email.text_body.strip():
        return email.text_body.strip()
    if email.html_body and email.html_body.strip():
        return re.sub(r'<[^>]+>', ' ', email.html_body).replace('&nbsp;', ' ').strip()
    return ''


def parse_email_with_deepseek(email):
    """
    Call DeepSeek API to parse email and return a dict of extracted fields.
    Returns dict with keys in PARSED_KEYS; on failure returns empty dict and logs.
    """
    api_key = getattr(settings, 'DEEPSEEK_API_KEY', None) or os.environ.get('DEEPSEEK_API_KEY', '')
    if not api_key:
        logger.warning('DEEPSEEK_API_KEY not set; skipping email parsing')
        return {}

    try:
        from openai import OpenAI
    except ImportError:
        logger.exception('openai package not installed')
        return {}

    text = _get_text_content(email)
    subject = (email.subject or '').strip()
    if not text and not subject:
        logger.info('No content to parse for email id=%s', email.pk)
        return {}

    user_content = f"From: {email.from_address or ''}\nSubject: {subject}\n\nBody:\n{text}"[:30000]

    client = OpenAI(
        api_key=api_key,
        base_url='https://api.deepseek.com',
    )
    response = client.chat.completions.create(
        model='deepseek-chat',
        messages=[
            {'role': 'system', 'content': SYSTEM_PROMPT},
            {'role': 'user', 'content': user_content},
        ],
        response_format={'type': 'json_object'},
        temperature=0.1,
    )
    raw = response.choices[0].message.content
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        logger.warning('DeepSeek returned invalid JSON: %s', e)
        return {}

    result = {}
    for key in PARSED_KEYS:
        val = data.get(key)
        if key == 'listing_profit':
            if val is None:
                result[key] = None
            elif isinstance(val, (int, float)):
                result[key] = val
            else:
                try:
                    s = str(val).strip().replace(',', '').replace('$', '')
                    result[key] = float(s) if s else None
                except (TypeError, ValueError):
                    result[key] = None
        elif val is None:
            result[key] = ''
        else:
            result[key] = str(val).strip() if val else ''
    result['_raw_parsed'] = data
    return result
