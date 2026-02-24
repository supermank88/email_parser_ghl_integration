"""
Management command to add AcroForm fields to NDA_Template.pdf and overwrite it.

Run after replacing NDA_Template.pdf with a new template:
  python manage.py add_nda_form_fields
"""

from django.core.management.base import BaseCommand

from inbound.pdf_nda import add_form_fields_to_template


class Command(BaseCommand):
    help = "Add form fields to NDA_Template.pdf and overwrite the file."

    def handle(self, *args, **options):
        try:
            add_form_fields_to_template()
            self.stdout.write(self.style.SUCCESS("NDA_Template.pdf overwritten with form fields."))
        except FileNotFoundError as e:
            self.stderr.write(self.style.ERROR(str(e)))
            raise SystemExit(1)
