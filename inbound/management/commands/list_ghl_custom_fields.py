"""
List GHL custom fields for the location (to find Signed NDA field ID).

Run: python manage.py list_ghl_custom_fields

Shows all custom fields including their IDs. Use this to verify
GHL_CUSTOM_FIELD_SIGNED_NDA matches a File Upload field for Contacts.
"""

import requests
from django.core.management.base import BaseCommand
from django.conf import settings


GHL_API_BASE = "https://services.leadconnectorhq.com"


class Command(BaseCommand):
    help = "List GHL custom fields for the location (find Signed NDA field ID)."

    def handle(self, *args, **options):
        api_key = getattr(settings, "GHL_API_KEY", None) or ""
        location_id = getattr(settings, "GHL_LOCATION_ID", None) or ""
        signed_nda_id = getattr(settings, "GHL_CUSTOM_FIELD_SIGNED_NDA", None) or ""

        if not api_key or not location_id:
            self.stderr.write(self.style.ERROR("GHL_API_KEY and GHL_LOCATION_ID required"))
            return

        url = f"{GHL_API_BASE}/locations/{location_id}/customFields"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Version": "2021-07-28",
            "Accept": "application/json",
        }

        try:
            resp = requests.get(url, headers=headers, timeout=15)
        except requests.RequestException as e:
            self.stderr.write(self.style.ERROR(f"Request failed: {e}"))
            return

        if resp.status_code != 200:
            self.stderr.write(
                self.style.ERROR(f"GHL returned {resp.status_code}: {resp.text[:500]}")
            )
            return

        data = resp.json()
        fields = data.get("customFields", data.get("customField", []))
        if isinstance(fields, dict):
            fields = list(fields.values()) if fields else []
        if not isinstance(fields, list):
            fields = [fields] if fields else []

        self.stdout.write(f"\nCustom Fields for location {location_id}")
        self.stdout.write(f"GHL_CUSTOM_FIELD_SIGNED_NDA = {repr(signed_nda_id)}\n")

        for f in fields:
            if not isinstance(f, dict):
                continue
            fid = f.get("id", f.get("field", ""))
            name = f.get("name", f.get("key", "?"))
            field_type = f.get("dataType", f.get("type", "?"))
            object_type = f.get("objectType", f.get("objectKey", "?"))
            is_match = str(fid) == str(signed_nda_id) if signed_nda_id else False
            marker = " <-- Signed NDA (current)" if is_match else ""
            self.stdout.write(f"  ID: {fid}")
            self.stdout.write(f"  Name: {name}{marker}")
            self.stdout.write(f"  Type: {field_type}  Object: {object_type}")
            self.stdout.write("")

        if signed_nda_id:
            matched = any(
                str(f.get("id", f.get("field", ""))) == str(signed_nda_id)
                for f in fields
                if isinstance(f, dict)
            )
            if not matched:
                self.stdout.write(
                    self.style.WARNING(
                        f"GHL_CUSTOM_FIELD_SIGNED_NDA ({signed_nda_id}) does not match any field above."
                    )
                )
