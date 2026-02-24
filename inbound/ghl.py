"""
GoHighLevel (GHL) contact sync.

Maps extracted lead fields to GHL contact:
- Standard: firstName, lastName (split from name), email, phone
- Custom fields: listing_id, listing_name, ref_id, lead_source, purchase_timeframe, amount_to_invest, lead_message

If a contact already exists (matched by listing_id and phone), we update it; otherwise we create via upsert.
All configuration (API key, location ID, custom field IDs) is read from settings, which loads from .env.
"""

import json
import logging
import re
import urllib.request
import urllib.error

from django.conf import settings

logger = logging.getLogger(__name__)

# GHL API v2 (v1 rest.gohighlevel.com returns 404)
GHL_API_BASE = "https://services.leadconnectorhq.com"

GHL_HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json",
    "Version": "2021-07-28",
    "User-Agent": "GHL-Automation/1.0 (Django; contact sync)",
}


def _split_name(full_name):
    """Split full name into first name and last name (GHL has separate fields)."""
    if not full_name or not isinstance(full_name, str):
        return "", ""
    parts = full_name.strip().split(None, 1)  # max 2 parts
    if not parts:
        return "", ""
    if len(parts) == 1:
        return parts[0][:255], ""
    return parts[0][:255], parts[1][:255]


def _normalize_phone(phone):
    """Return E.164-style phone (GHL search often expects E.164)."""
    if not phone or not isinstance(phone, str):
        return ""
    digits = re.sub(r"\D", "", phone.strip())
    if not digits:
        return ""
    if len(digits) == 10:
        return "+1" + digits  # US/Canada without country code
    if len(digits) == 11 and digits.startswith("1"):
        return "+" + digits
    return "+" + digits


def _ghl_request(api_key, method, path, data=None):
    """Make a request to GHL API; returns (status_code, response_dict or None)."""
    url = f"{GHL_API_BASE}{path}"
    headers = {**GHL_HEADERS, "Authorization": f"Bearer {api_key}"}
    body = json.dumps(data).encode("utf-8") if data is not None else None
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = resp.read().decode()
            return resp.status, (json.loads(raw) if raw.strip() else {})
    except urllib.error.HTTPError as e:
        raw = e.read().decode()
        try:
            return e.code, json.loads(raw) if raw.strip() else {}
        except Exception:
            return e.code, {}
    except (OSError, ValueError) as e:
        logger.debug("GHL request error: %s", e)
        return -1, None


def _search_contact_by_phone_and_listing(api_key, location_id, phone, listing_id):
    """
    Search for an existing contact by phone and optionally listing_id.
    Returns contact id (str) if exactly one match that also matches listing_id when provided; else None.
    """
    if not phone and not listing_id:
        return None
    # GHL search often expects E.164 phone
    query_phone = _normalize_phone(phone) if phone else ""
    # Build search body: common patterns are query or phone filter
    body = {"locationId": location_id}
    if query_phone:
        body["phone"] = query_phone
    if listing_id and not query_phone:
        # If only listing_id, search by query string (listing_id value)
        body["query"] = (listing_id or "").strip()[:100]
    elif listing_id and query_phone:
        body["query"] = query_phone  # prefer phone search when both present

    status, data = _ghl_request(api_key, "POST", "/contacts/search", body)
    if status != 200 or data is None:
        return None
    contacts = data.get("contacts") or data.get("contact") or []
    if isinstance(contacts, dict):
        contacts = [contacts]
    if not contacts:
        return None
    listing_id_str = (listing_id or "").strip()
    listing_field_id = getattr(settings, "GHL_CUSTOM_FIELD_LISTING_ID", None) or ""

    def _contact_has_listing_id(contact):
        if not listing_id_str or not listing_field_id:
            return True
        custom = contact.get("customFields") or contact.get("customField") or []
        if isinstance(custom, dict):
            custom = list(custom.values()) if custom else []
        for cf in custom:
            if not isinstance(cf, dict):
                continue
            if cf.get("id") == listing_field_id or cf.get("field") == listing_field_id:
                if str(cf.get("value") or "").strip() == listing_id_str:
                    return True
        return False

    for c in contacts:
        cid = c.get("id")
        if not cid:
            continue
        if _contact_has_listing_id(c):
            return cid
    return None


def _custom_fields(email, include_empty_ref_id=False):
    """Build customFields array for GHL from InboundEmail and settings.
    When include_empty_ref_id is True, always include ref_id when env is set (so update overwrites it).
    """
    out = []
    cfg = settings
    # listing_id -> contact.listing_id
    if getattr(cfg, "GHL_CUSTOM_FIELD_LISTING_ID", None) and email.listing_id:
        out.append({"id": cfg.GHL_CUSTOM_FIELD_LISTING_ID, "value": email.listing_id})
    # listing_name -> contact.listing_name
    if getattr(cfg, "GHL_CUSTOM_FIELD_LISTING_NAME", None) and email.listing_name:
        out.append({"id": cfg.GHL_CUSTOM_FIELD_LISTING_NAME, "value": email.listing_name})
    # ref_id - always include when env set if include_empty_ref_id (for updates)
    if getattr(cfg, "GHL_CUSTOM_FIELD_REF_ID", None):
        if email.ref_id or include_empty_ref_id:
            out.append({"id": cfg.GHL_CUSTOM_FIELD_REF_ID, "value": (email.ref_id or "").strip()})
    # lead_source
    if getattr(cfg, "GHL_CUSTOM_FIELD_LEAD_SOURCE", None) and email.lead_source:
        out.append({"id": cfg.GHL_CUSTOM_FIELD_LEAD_SOURCE, "value": email.lead_source})
    # purchase_timeframe
    if getattr(cfg, "GHL_CUSTOM_FIELD_PURCHASE_TIMEFRAME", None) and email.purchase_timeframe:
        out.append({"id": cfg.GHL_CUSTOM_FIELD_PURCHASE_TIMEFRAME, "value": email.purchase_timeframe})
    # amount_to_invest
    if getattr(cfg, "GHL_CUSTOM_FIELD_AMOUNT_TO_INVEST", None) and email.amount_to_invest:
        out.append({"id": cfg.GHL_CUSTOM_FIELD_AMOUNT_TO_INVEST, "value": email.amount_to_invest})
    # lead_message (may be long; GHL text area supports up to 5000)
    if getattr(cfg, "GHL_CUSTOM_FIELD_LEAD_MESSAGE", None) and email.lead_message:
        out.append({"id": cfg.GHL_CUSTOM_FIELD_LEAD_MESSAGE, "value": (email.lead_message or "")[:5000]})
    return out


def sync_contact_to_ghl(email):
    """
    Create or update a GHL contact from an InboundEmail (after parsing).

    Syncs only when listing_id, phone, and lead_source are all present.
    If a contact exists (matched by listing_id and phone), we update it; otherwise we create via upsert.
    Maps: name -> firstName, lastName; email, phone; custom fields.
    Returns GHL contact id (string) on success, None if disabled or on error.
    """
    api_key = getattr(settings, "GHL_API_KEY", None) or ""
    location_id = getattr(settings, "GHL_LOCATION_ID", None) or ""
    if not api_key or not location_id:
        logger.debug("GHL sync skipped: GHL_API_KEY or GHL_LOCATION_ID not set")
        return None

    listing_id_str = (email.listing_id or "").strip()
    phone_raw = (email.phone or "").strip()
    lead_source_str = (email.lead_source or "").strip()
    if not listing_id_str or not phone_raw:
        logger.debug(
            "GHL sync skipped: need both listing_id and phone (got listing_id=%r, phone=%r) for inbound email id=%s",
            listing_id_str or None,
            phone_raw or None,
            email.pk,
        )
        return None
    if not lead_source_str:
        logger.debug("GHL sync skipped: lead_source not extracted for inbound email id=%s", email.pk)
        return None

    first_name, last_name = _split_name(email.name)
    phone_e164 = _normalize_phone(phone_raw) or phone_raw or None
    payload = {
        "locationId": location_id,
        "firstName": first_name,
        "lastName": last_name,
        "email": (email.email or "").strip() or None,
        "phone": phone_e164 or None,
        "source": email.lead_source or None,
    }
    custom = _custom_fields(email)
    if custom:
        payload["customFields"] = custom

    # Try to find an existing contact and update it
    existing_id = _search_contact_by_phone_and_listing(
        api_key, location_id, phone_raw or None, listing_id_str or None
    )
    if existing_id:
        # For update: always send ref_id (and custom fields) so GHL overwrites existing contact
        update_custom = _custom_fields(email, include_empty_ref_id=True)
        update_payload = {**payload}
        if update_custom:
            update_payload["customFields"] = update_custom
        status, data = _ghl_request(api_key, "PUT", f"/contacts/{existing_id}", update_payload)
        if status == 200:
            contact_id = data.get("contact", {}).get("id") or data.get("id") or existing_id
            logger.info("GHL contact updated for inbound email id=%s, GHL contact id=%s", email.pk, contact_id)
            return contact_id
        logger.warning("GHL contact update failed: status=%s body=%s", status, data)

    # Create or upsert
    status, data = _ghl_request(api_key, "POST", "/contacts/upsert", payload)
    if status in (200, 201):
        contact_id = (data.get("contact") or {}).get("id") or data.get("id")
        logger.info("GHL contact upserted for inbound email id=%s, GHL contact id=%s", email.pk, contact_id)
        return contact_id
    logger.warning(
        "GHL upsert failed: status=%s body=%s. "
        "If 403/1010: ensure GHL_API_KEY is valid and has contacts write scope.",
        status,
        str(data)[:500] if data else "",
    )
    return None
