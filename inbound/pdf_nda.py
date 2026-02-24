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
# Original clean template at project root; copied here before adding form fields
ORIGINAL_NDA_TEMPLATE_PATH = BASE_DIR / "NDA_Template.pdf"

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
    ("listing_id", 158, 113, 200, 127),   # shifted right
    ("listing_name", 287, 113, 585, 127),
    # Clause 9: ... Explain: _______________________ if line is blank
    ("govt_explain", 410, 403, 500, 414),  # narrower width
    # Name (print clearly): x_____________________________________  Signature: ___________________________
    ("name", 130, 452, 243, 462),   # shifted left
    ("signature", 416, 452, 552, 462),
    # Street Address_____________________________________________ City_____________ State_________ Zip_____________
    ("street_address", 100, 476, 310, 486),
    ("city", 342, 476, 410, 486),   # shifted left
    ("state", 430, 476, 460, 486),  # shifted left
    ("zip", 490, 476, 552, 486),
    # Email: x____________________________________________ Cell#: _______________________
    ("email", 80, 506, 288, 516),
    ("cell", 318, 506, 490, 516),   # shifted left
    # I have a Partner, Partner's Name: __________
    ("partner_name", 211, 631, 285, 645),
]

# Dropdown (combo) fields: "Choose an item" as default label, then real options.
NDA_CHOICE_FIELDS = [
    ("govt_affiliation", 265, 403, 342, 414, ["Choose an item", "Yes", "No", "N/A"]),
    ("will_manage", 167, 525, 250, 537, ["Choose an item", "Yes", "No"]),
    ("other_deciders", 115, 539, 177, 550, ["Choose an item", "Yes", "No", "N/A"]),
    ("industry_experience", 168, 561, 250, 573, ["Choose an item", "Yes", "No"]),
    ("timeframe", 453, 561, 553, 573, ["Choose an item", "0-3 months", "3-6 months", "6-12 months", "12+ months"]),
    ("liquid_assets", 203, 599, 340, 611, ["Choose an item", "Under $50k", "$50k-$250k", "$250k+"]),
    ("real_estate", 443, 599, 520, 611, ["Choose an item", "Yes", "No"]),
    ("retirement_401k", 182, 616, 340, 628, ["Choose an item", "Yes", "No"]),
    ("funds_for_business", 500, 616, 593, 628, ["Choose an item", "Yes", "No", "Partial"]),
    ("using", 358, 631, 458, 645, ["Choose an item", "Personal funds", "Partner", "Loan", "Other"]),
]


def _redact_choose_an_item_text(page: "fitz.Page") -> None:
    """Remove printed 'Choose an item' / 'Choose an item.' labels from the page."""
    for phrase in ("Choose an item.", "Choose an item"):
        quads = page.search_for(phrase, quads=True)
        for q in quads:
            page.add_redact_annot(q.rect, fill=(1, 1, 1))  # white cover
    if page.first_annot:
        page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE, graphics=fitz.PDF_REDACT_LINE_ART_NONE)


def add_form_fields_to_template():
    """
    Open NDA_Template.pdf, remove any existing form widgets, add widgets at exact
    positions (wrap for exact location), save and overwrite.
    Uses ORIGINAL_NDA_TEMPLATE_PATH (project root) as source if present, so layout
    matches the original (e.g. "Explain:" is preserved).
    """
    # Start from original template if provided at project root
    if ORIGINAL_NDA_TEMPLATE_PATH.exists():
        import shutil
        NDA_TEMPLATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ORIGINAL_NDA_TEMPLATE_PATH, NDA_TEMPLATE_PATH)
    if not NDA_TEMPLATE_PATH.exists():
        raise FileNotFoundError(f"Template not found: {NDA_TEMPLATE_PATH}")

    doc = fitz.open(NDA_TEMPLATE_PATH)
    page = doc[0]

    # Remove printed "Choose an item" labels (quads only; preserves "Explain:" on clause 9)
    _redact_choose_an_item_text(page)

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

    for item in NDA_CHOICE_FIELDS:
        if len(item) != 6:
            continue
        field_name, x0, y0_top, x1, y1_top, choices = item
        if len(choices) < 2:
            continue
        rect = _rect_top_left(x0, y0_top, x1, y1_top)
        widget = fitz.Widget()
        widget.rect = rect
        widget.field_type = fitz.PDF_WIDGET_TYPE_COMBOBOX
        widget.field_name = field_name
        widget.choice_values = list(choices)
        widget.field_value = choices[0]  # default label: "Choose an item"
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

    # Choice fields: when empty, use "Choose an item" so it shows as label until user selects.
    _default_choice = "Choose an item"
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
        "will_manage": will_manage or _default_choice,
        "other_deciders": other_deciders or _default_choice,
        "industry_experience": industry_experience or _default_choice,
        "timeframe": timeframe or _default_choice,
        "liquid_assets": liquid_assets or _default_choice,
        "real_estate": real_estate or _default_choice,
        "retirement_401k": retirement_401k or _default_choice,
        "funds_for_business": funds_for_business or _default_choice,
        "partner_name": partner_name or "",
        "using": using or _default_choice,
        "govt_affiliation": govt_affiliation or _default_choice,
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
