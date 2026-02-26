"""
GoHighLevel (GHL) contact sync and media upload.

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
from pathlib import Path

import requests

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
    Search for an existing contact that matches BOTH phone AND listing_id.
    Does two separate API searches (by phone, by listing_id), then returns a contact id
    only if it appears in both result sets and has both fields matching. Otherwise None
    so caller will create a new contact.
    """
    if not phone and not listing_id:
        return None
    query_phone = _normalize_phone(phone) if phone else ""
    listing_str = (listing_id or "").strip()[:100]
    listing_field_id = getattr(settings, "GHL_CUSTOM_FIELD_LISTING_ID", None) or ""

    def _run_search(phone_only=False, query_only=None):
        body = {"locationId": location_id}
        if phone_only and query_phone:
            body["phone"] = query_phone
        if query_only is not None:
            body["query"] = query_only[:100]
        status, data = _ghl_request(api_key, "POST", "/contacts/search", body)
        if status != 200 or data is None:
            return []
        contacts = data.get("contacts") or data.get("contact") or []
        if isinstance(contacts, dict):
            contacts = [contacts]
        return contacts

    # Require both to match: get contacts that have this phone AND contacts that have this listing_id
    by_phone = {c.get("id"): c for c in _run_search(phone_only=True) if c.get("id")} if query_phone else {}
    by_listing = {c.get("id"): c for c in _run_search(query_only=listing_str) if c.get("id")} if listing_str else {}

    # When we have both phone and listing_id: contact must be in BOTH result sets
    if query_phone and listing_str:
        common_ids = set(by_phone.keys()) & set(by_listing.keys())
    elif query_phone:
        common_ids = set(by_phone.keys())
    elif listing_str:
        common_ids = set(by_listing.keys())
    else:
        return None

    def _get_contact(cid):
        return by_phone.get(cid) or by_listing.get(cid)

    def _contact_matches_phone(contact, expected_phone):
        if not expected_phone:
            return True
        raw = contact.get("phone") or contact.get("phoneNumber")
        if not raw:
            # GHL sometimes returns phones as array
            phones = contact.get("phones") or []
            for p in phones if isinstance(phones, list) else []:
                if isinstance(p, dict) and p.get("number"):
                    raw = p.get("number")
                    break
                elif isinstance(p, str):
                    raw = p
                    break
        contact_phone = (raw or "").strip()
        if not contact_phone:
            return False
        n_contact = _normalize_phone(contact_phone)
        n_expected = expected_phone if expected_phone.startswith("+") else _normalize_phone(expected_phone)
        return n_contact == n_expected or contact_phone == expected_phone

    def _contact_has_listing_id(contact):
        if not listing_str or not listing_field_id:
            return True
        custom = contact.get("customFields") or contact.get("customField") or []
        if isinstance(custom, dict):
            custom = list(custom.values()) if custom else []
        for cf in custom:
            if not isinstance(cf, dict):
                continue
            if cf.get("id") == listing_field_id or cf.get("field") == listing_field_id:
                if str(cf.get("value") or "").strip() == listing_str:
                    return True
        return False

    for cid in common_ids:
        c = _get_contact(cid)
        if not c:
            continue
        if not _contact_matches_phone(c, query_phone or phone):
            continue
        if not _contact_has_listing_id(c):
            continue
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
    Create a new GHL contact from an InboundEmail (after parsing).
    Only runs when listing_name, name, phone, and lead_source are all present. No search for existing contacts.
    Returns GHL contact id (string) on success, None if disabled or on error.
    """
    api_key = getattr(settings, "GHL_API_KEY", None) or ""
    location_id = getattr(settings, "GHL_LOCATION_ID", None) or ""
    if not api_key or not location_id:
        logger.info(
            "GHL sync skipped: GHL_API_KEY or GHL_LOCATION_ID not set (check .env). email id=%s",
            email.pk,
        )
        return None

    listing_name_str = (email.listing_name or "").strip()
    name_str = (email.name or "").strip()
    phone_raw = (email.phone or "").strip()
    lead_source_str = (email.lead_source or "").strip()
    if not listing_name_str or not name_str or not phone_raw:
        logger.info(
            "GHL sync skipped: need listing_name, name, and phone (got listing_name=%r, name=%r, phone=%r). email id=%s",
            listing_name_str or None,
            name_str or None,
            phone_raw or None,
            email.pk,
        )
        return None
    if not lead_source_str:
        logger.info(
            "GHL sync skipped: lead_source not extracted. email id=%s",
            email.pk,
        )
        return None

    first_name, last_name = _split_name(email.name or "")
    phone_e164 = _normalize_phone(phone_raw) or phone_raw or None
    email_addr = (email.email or "").strip() or None

    payload = {
        "locationId": location_id,
        "firstName": first_name or "Unknown",
        "lastName": last_name or "",
        "email": email_addr,
        "phone": phone_e164,
        "source": (email.lead_source or "").strip() or "Inbound Email",
    }
    custom = _custom_fields(email)
    if custom:
        payload["customFields"] = custom

    # Create new contact only (POST /contacts/), not upsert, so we don't match existing by email/phone
    status, data = _ghl_request(api_key, "POST", "/contacts/", payload)
    if status in (200, 201):
        contact_id = (data.get("contact") or {}).get("id") or data.get("id")
        if contact_id:
            logger.info("GHL contact created for inbound email id=%s, GHL contact id=%s", email.pk, contact_id)
            return contact_id
        logger.warning("GHL POST /contacts/ returned %s but no contact id in response: %s", status, data)
    else:
        logger.warning(
            "GHL create failed: status=%s body=%s. Check API key scope and locationId.",
            status,
            str(data)[:500] if data else "",
        )
    return None


def _get_signed_nda_folder_id(api_key, location_id):
    """
    Get or create the Signed_NDA folder in GHL Media Storage.
    Returns folder ID (str) or None on failure.
    """
    # List root media files/folders (try common endpoints)
    for path in [f"/medias/files?locationId={location_id}", f"/medias?locationId={location_id}"]:
        status, data = _ghl_request(api_key, "GET", path)
        if status == 200 and data is not None:
            break
    if status != 200 or data is None:
        logger.warning("GHL list media failed: status=%s", status)
        return None

    # Response may have 'medias', 'files', or 'folders'
    items = data.get("medias") or data.get("files") or data.get("folders") or []
    if isinstance(items, dict):
        items = items.get("medias") or items.get("files") or items.get("folders") or []
    if not isinstance(items, list):
        items = []

    for item in items:
        if not isinstance(item, dict):
            continue
        name = (item.get("name") or item.get("title") or "").strip()
        folder_name = getattr(settings, "GHL_SIGNED_NDA_FOLDER", None) or "Signed_NDA"
        if name == folder_name:
            fid = item.get("id") or item.get("_id")
            if fid:
                return str(fid)

    # Create folder
    folder_name = getattr(settings, "GHL_SIGNED_NDA_FOLDER", None) or "Signed_NDA"
    create_body = {"locationId": location_id, "name": folder_name}
    status, data = _ghl_request(api_key, "POST", "/medias/folder", create_body)
    if status not in (200, 201) or data is None:
        logger.warning("GHL create folder failed: status=%s body=%s", status, str(data)[:300] if data else "")
        return None

    folder = data.get("folder") or data.get("media") or data
    fid = folder.get("id") if isinstance(folder, dict) else None
    if fid:
        logger.info("Created GHL folder %s", folder_name)
        return str(fid)
    return None


def upload_nda_to_ghl_media(filepath, filename, contact_id, contact):
    """
    Upload a signed NDA PDF to GHL Media Storage in the Signed_NDA folder.

    Args:
        filepath: Path to the PDF file on disk
        filename: Display filename (e.g. nda_signed_listing_contact_ts.pdf)
        contact_id: GHL contact ID (for logging)
        contact: InboundEmail instance (for location_id via ghl_contact_id lookup if needed)

    Returns:
        str: GHL media/file ID on success, None on failure.
    """
    api_key = getattr(settings, "GHL_API_KEY", None) or ""
    location_id = getattr(settings, "GHL_LOCATION_ID", None) or ""
    if not api_key or not location_id:
        logger.info("GHL media upload skipped: GHL_API_KEY or GHL_LOCATION_ID not set")
        return None

    path = Path(filepath)
    if not path.exists() or not path.is_file():
        logger.warning("NDA file not found for GHL upload: %s", filepath)
        return None

    folder_id = _get_signed_nda_folder_id(api_key, location_id)
    if not folder_id:
        logger.warning("Could not get/create Signed_NDA folder; uploading to root")

    url = f"{GHL_API_BASE}/medias/upload-file"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Version": "2021-07-28",
        "Accept": "application/json",
    }
    # Do NOT set Content-Type; requests will set multipart/form-data with boundary

    try:
        with open(path, "rb") as f:
            files = {"file": (filename, f, "application/pdf")}
            data = {"locationId": location_id, "name": filename}
            if folder_id:
                data["folderId"] = folder_id
            resp = requests.post(url, headers=headers, files=files, data=data, timeout=30)
    except OSError as e:
        logger.exception("Failed to read NDA file for GHL upload: %s", e)
        return None
    except requests.RequestException as e:
        logger.exception("GHL media upload request failed: %s", e)
        return None

    if resp.status_code not in (200, 201):
        logger.warning(
            "GHL media upload failed: status=%s body=%s",
            resp.status_code,
            resp.text[:500] if resp.text else "",
        )
        return None

    try:
        body = resp.json()
    except Exception:
        body = {}

    media_id = (
        (body.get("media") or {}).get("id")
        or (body.get("file") or {}).get("id")
        or body.get("id")
    )
    if media_id:
        logger.info(
            "Uploaded signed NDA to GHL Media (Signed_NDA): contact=%s file=%s media_id=%s",
            contact_id,
            filename,
            media_id,
        )
        return str(media_id)

    logger.warning("GHL upload returned success but no media id: %s", body)
    return None
