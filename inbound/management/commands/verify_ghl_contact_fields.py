"""
Verify GHL contact custom fields (for debugging Signed NDA upload).

Run: python manage.py verify_ghl_contact_fields CONTACT_ID

Fetches the contact from GHL and prints custom fields, including the Signed NDA
field if present. Use this to confirm uploads and verify GHL_CUSTOM_FIELD_SIGNED_NDA.
"""

import json

import requests
from django.core.management.base import BaseCommand
from django.conf import settings


GHL_API_BASE = "https://services.leadconnectorhq.com"


class Command(BaseCommand):
    help = "Fetch a GHL contact and display custom fields (for debugging NDA upload)."

    def add_arguments(self, parser):
        parser.add_argument("contact_id", help="GHL contact ID")
        parser.add_argument(
            "--signed-nda-field",
            default=getattr(settings, "GHL_CUSTOM_FIELD_SIGNED_NDA", "") or "",
            help="Custom field ID for Signed NDA (default: from settings)",
        )

    def handle(self, *args, **options):
        contact_id = options["contact_id"]
        field_id = (options["signed_nda_field"] or "").strip()
        api_key = getattr(settings, "GHL_API_KEY", None) or ""
        location_id = getattr(settings, "GHL_LOCATION_ID", None) or ""

        if not api_key:
            self.stderr.write(self.style.ERROR("GHL_API_KEY not set"))
            return

        url = f"{GHL_API_BASE}/contacts/{contact_id}"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Version": "2021-07-28",
            "Accept": "application/json",
        }
        params = {}
        if location_id:
            params["locationId"] = location_id

        try:
            resp = requests.get(url, headers=headers, params=params, timeout=15)
        except requests.RequestException as e:
            self.stderr.write(self.style.ERROR(f"Request failed: {e}"))
            return

        if resp.status_code != 200:
            self.stderr.write(
                self.style.ERROR(f"GHL returned {resp.status_code}: {resp.text[:500]}")
            )
            return

        data = resp.json()
        contact = data.get("contact", data)

        self.stdout.write(f"\nContact: {contact.get('id')}")
        self.stdout.write(f"Name: {contact.get('firstName', '')} {contact.get('lastName', '')}")
        self.stdout.write(f"Email: {contact.get('email', '')}")
        self.stdout.write(f"\nCustom Fields (GHL_CUSTOM_FIELD_SIGNED_NDA={field_id or '(not set)'}):\n")

        custom = contact.get("customFields", contact.get("customField", []))
        if isinstance(custom, dict):
            custom = list(custom.values()) if custom else []
        if not isinstance(custom, list):
            custom = [custom] if custom else []

        if not custom:
            self.stdout.write(self.style.WARNING("  No custom fields on contact"))
            return

        for cf in custom:
            if not isinstance(cf, dict):
                continue
            cid = cf.get("id") or cf.get("field") or cf.get("key", "")
            name = cf.get("name", cf.get("key", "?"))
            val = cf.get("value", "")
            is_signed_nda = str(cid) == str(field_id) if field_id else False
            marker = " <-- Signed NDA field" if is_signed_nda else ""
            self.stdout.write(f"  ID: {cid}")
            self.stdout.write(f"  Name: {name}{marker}")
            self.stdout.write(f"  Value: {str(val)[:200]}{'...' if len(str(val)) > 200 else ''}")
            self.stdout.write("")
