"""
Fillable NDA template and render with populated values.

Template: inbound/static/inbound/NDA_Template.pdf is the fillable PDF (saved as template).
- You can generate it: run `python manage.py add_nda_form_fields` to create form fields
  on the current PDF and overwrite the template.
- Or replace the file with your own fillable PDF (e.g. from Acrobat); keep field names
  ref_id, listing_id, listing_name, name, signature, street_address, city, state, zip,
  email, cell, will_manage, other_deciders, industry_experience, timeframe, liquid_assets,
  real_estate, retirement_401k, funds_for_business, partner_name, using, govt_affiliation, govt_explain.

Render: fill_nda_pdf(...) uses pypdf to fill form field values only, so the rest of the
PDF (body text, fonts, layout) is preserved and not re-encoded (avoids garbled text).
"""

import os
from io import BytesIO
from pathlib import Path

import fitz  # PyMuPDF (for add_form_fields only)
from pypdf import PdfReader, PdfWriter
from pypdf.constants import FieldDictionaryAttributes as FA
from pypdf.generic import NameObject, NumberObject

# Path to the template (static: inbound/static/inbound/NDA_Template.pdf)
BASE_DIR = Path(__file__).resolve().parent.parent
NDA_TEMPLATE_PATH = BASE_DIR / "inbound" / "static" / "inbound" / "NDA_Template.pdf"

# PDF page size (letter)
PAGE_W, PAGE_H = 612, 792


def _rect_top_left(x0, y0_top, x1, y1_top):
    """Return fitz Rect in top-left coords (PyMuPDF uses top-left origin, y down)."""
    return fitz.Rect(x0, y0_top, x1, y1_top)


# Form field definitions: (field_name, rect in top-left coords x0, y0_top, x1, y1_top)
# Exact locations from template so fields wrap the blank/underline areas (Tupelo-style).
NDA_FIELDS = [
    # Top line: # _________  Listing#_______  Listing Name: _________________________________
    ("ref_id", 45, 113, 108, 127),
    ("listing_id", 120, 113, 200, 127),
    ("listing_name", 287, 113, 585, 127),
    # Clause 9: ... Explain: _______________________ if line is blank
    ("govt_affiliation", 352, 403, 420, 414),
    ("govt_explain", 420, 403, 550, 414),
    # Name (print clearly): x_____________________________________  Signature: ___________________________
    ("name", 250, 452, 345, 462),
    ("signature", 416, 452, 552, 462),
    # Street Address_____________________________________________ City_____________ State_________ Zip_____________
    ("street_address", 180, 476, 320, 486),
    ("city", 404, 476, 450, 486),
    ("state", 452, 476, 473, 486),
    ("zip", 475, 476, 552, 486),
    # Email: x____________________________________________ Cell#: _______________________
    ("email", 80, 506, 288, 516),
    ("cell", 430, 506, 520, 516),
    # I Will Manage Business: Choose an item.
    ("will_manage", 227, 525, 350, 537),
    # Other Deciders: Choose an item.
    ("other_deciders", 185, 539, 350, 550),
    # I have Industry experience: ___  Timeframe to purchase: Choose an item.
    ("industry_experience", 168, 561, 280, 573),
    ("timeframe", 413, 561, 553, 573),
    # Liquid Assets (cash, stocks, bonds) $ ___     Real Estate $ ___
    ("liquid_assets", 203, 599, 340, 611),
    ("real_estate", 443, 599, 520, 611),
    # 401K, SEP, SIMPLE, Roth, IRA $ ___     Funds for this business: Choose an item.
    ("retirement_401k", 182, 616, 340, 628),
    ("funds_for_business", 500, 616, 593, 628),
    # I have a Partner, Partner's Name: __________   I'm using: Choose an item.
    ("partner_name", 216, 631, 285, 645),
    ("using", 358, 631, 458, 645),
]


def add_form_fields_to_template():
    """
    Open NDA_Template.pdf, remove any existing form widgets, add widgets at exact
    positions (wrap for exact location), save and overwrite.
    """
    if not NDA_TEMPLATE_PATH.exists():
        raise FileNotFoundError(f"Template not found: {NDA_TEMPLATE_PATH}")

    doc = fitz.open(NDA_TEMPLATE_PATH)
    page = doc[0]

    # Remove existing widgets so fields wrap exact locations (no duplicate/offset)
    widget = page.first_widget
    while widget is not None:
        next_w = widget.next
        page.delete_widget(widget)
        widget = next_w

    for item in NDA_FIELDS:
        if len(item) == 5:
            field_name, x0, y0_top, x1, y1_top = item
        else:
            continue
        rect = _rect_top_left(x0, y0_top, x1, y1_top)
        widget = fitz.Widget()
        widget.rect = rect
        widget.field_type = fitz.PDF_WIDGET_TYPE_TEXT
        widget.field_name = field_name
        widget.field_value = ""
        widget.text_fontsize = 9
        page.add_widget(widget)

    tmp_path = NDA_TEMPLATE_PATH.with_suffix(".pdf.tmp")
    # Preserve existing content: avoid clean=True to reduce re-encoding of body text/fonts
    doc.save(tmp_path, clean=False, deflate=False, garbage=0)
    doc.close()
    os.replace(tmp_path, NDA_TEMPLATE_PATH)
    return True


def fill_nda_pdf(contact_id=None, listing_id="", listing_name="", name="", email="", phone="",
                 ref_id="", street_address="", city="", state="", zip_code="", signature="",
                 will_manage="", other_deciders="", industry_experience="", timeframe="",
                 liquid_assets="", real_estate="", retirement_401k="", funds_for_business="",
                 partner_name="", using="", govt_affiliation="", govt_explain="", **kwargs):
    """
    Load fillable NDA_Template.pdf, set form field values with pypdf (preserves all other
    PDF content so body text and fonts are not corrupted), return PDF bytes.
    """
    if not NDA_TEMPLATE_PATH.exists():
        raise FileNotFoundError(f"Template not found: {NDA_TEMPLATE_PATH}")

    value_map = {
        "ref_id": ref_id or "",
        "listing_id": listing_id or "",
        "listing_name": listing_name or "",
        "name": name or "",
        "signature": signature or "",
        "street_address": street_address or "",
        "city": city or "",
        "state": state or "",
        "zip": zip_code or "",
        "email": email or "",
        "cell": phone or "",
        "will_manage": will_manage or "",
        "other_deciders": other_deciders or "",
        "industry_experience": industry_experience or "",
        "timeframe": timeframe or "",
        "liquid_assets": liquid_assets or "",
        "real_estate": real_estate or "",
        "retirement_401k": retirement_401k or "",
        "funds_for_business": funds_for_business or "",
        "partner_name": partner_name or "",
        "using": using or "",
        "govt_affiliation": govt_affiliation or "",
        "govt_explain": govt_explain or "",
    }
    if contact_id and not value_map["ref_id"]:
        value_map["ref_id"] = str(contact_id)[:50]
    # Truncate long values so they fit in typical field width
    for k in value_map:
        value_map[k] = str(value_map[k])[:255]

    reader = PdfReader(NDA_TEMPLATE_PATH)
    writer = PdfWriter()
    # Append only (no clone_reader_document_root) to avoid duplicating pages
    writer.append(reader)
    # PyMuPDF-created forms may have fields only in page /Annots; reattach builds /Fields
    writer.reattach_fields()
    writer.set_need_appearances_writer(True)
    writer.update_page_form_field_values(writer.pages[0], value_map, auto_regenerate=False)
    # Clear ReadOnly on all form fields so the PDF remains editable
    _clear_readonly_fields(writer)
    buffer = BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def _clear_readonly_fields(writer: PdfWriter) -> None:
    """Clear the ReadOnly bit on all form fields so the PDF can be edited in viewers."""
    try:
        af = writer._root_object.get(NameObject("/AcroForm"))
        if af is None:
            return
        fields_arr = af.get(NameObject("/Fields"))
        if fields_arr is None:
            return
        for ref in fields_arr:
            obj = ref.get_object()
            if obj is None:
                continue
            if NameObject(FA.Ff) in obj:
                obj[NameObject(FA.Ff)] = NumberObject(int(obj[FA.Ff]) & ~FA.FfBits.ReadOnly)
            # Recurse into /Kids if present
            if NameObject(FA.Kids) in obj:
                for kid_ref in obj[FA.Kids]:
                    kid = kid_ref.get_object()
                    if kid is not None and NameObject(FA.Ff) in kid:
                        kid[NameObject(FA.Ff)] = NumberObject(int(kid[FA.Ff]) & ~FA.FfBits.ReadOnly)
    except Exception:
        pass
