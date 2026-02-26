# GHL Automation – SendGrid Inbound Email

Django project that receives inbound email via **SendGrid Inbound Parse** and exposes a webhook endpoint for processing.

## Setup

### 1. Create and activate a virtual environment

```bash
cd ghl_automation
python3 -m venv .venv
source .venv/bin/activate   # Linux/macOS
# or: .venv\Scripts\activate  # Windows
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Run migrations (optional; no models are used by default)

```bash
python manage.py migrate
```

### 4. Configure DeepSeek (for email parsing)

Copy `.env.example` to `.env` and set your DeepSeek API key:

```bash
cp .env.example .env
# Edit .env and set: DEEPSEEK_API_KEY=your_api_key
```

Get an API key from [DeepSeek Platform](https://platform.deepseek.com/). If `DEEPSEEK_API_KEY` is not set, inbound emails are still saved but parsed fields will be empty.

### 5. Run the development server

```bash
python manage.py runserver
```

The SendGrid webhook URL will be:

- **Local:** `http://localhost:8000/sendgrid/webhook/inbound/`
- **Production:** `https://your-domain.com/sendgrid/webhook/inbound/`

For local testing with SendGrid, use a tunnel (e.g. [ngrok](https://ngrok.com/)) so SendGrid can reach your machine.

## manage.py commands

| Command | Description |
|---------|-------------|
| `python manage.py migrate` | Run database migrations |
| `python manage.py runserver` | Start the development server |
| `python manage.py add_nda_form_fields` | Add fillable form fields to the NDA PDF template (see below) |
| `python manage.py fix_received_at_timezone` | Fix naive `received_at` timestamps for correct EST display |
| `python manage.py verify_ghl_contact_fields <id>` | Fetch GHL contact and show custom fields (debug NDA upload) |
| `python manage.py list_ghl_custom_fields` | List location custom fields and IDs (find Signed NDA field) |

### Updating the NDA PDF template

The NDA viewer uses a fillable PDF at `inbound/static/inbound/NDA_Template.pdf`. To update or rebuild it:

1. **Option A – Use a clean template at project root**  
   Place your clean NDA PDF (no form fields) as `NDA_Template.pdf` in the project root. Then run:
   ```bash
   python manage.py add_nda_form_fields
   ```
   This copies the clean template into static, adds AcroForm fields (text inputs and dropdowns for ref_id, listing_id, listing_name, name, email, phone, etc.), and overwrites `inbound/static/inbound/NDA_Template.pdf`.

2. **Option B – Use your own fillable PDF**  
   Replace `inbound/static/inbound/NDA_Template.pdf` with your own fillable PDF (e.g. from Adobe Acrobat). Ensure field names match: `ref_id`, `listing_id`, `listing_name`, `name`, `email`, `cell`, `signature`, `street_address`, `city`, `state`, `zip`, and the choice fields (`will_manage`, `other_deciders`, `industry_experience`, etc.).    See `inbound/pdf_nda.py` for the full list.

## SendGrid Inbound Parse configuration

1. In [SendGrid](https://app.sendgrid.com/), go to **Settings → Inbound Parse**.
2. Click **Add Host & URL**.
3. Set:
   - **Destination URL:** `https://your-domain.com/inbound/webhook/sendgrid/`
   - **HTTP POST URL:** same as above (SendGrid POSTs the parsed email here).
4. Configure the domain/subdomain that will receive email (MX records as shown by SendGrid).
5. Save. Incoming mail to that address will be POSTed to your Django endpoint.

## Webhook payload

SendGrid sends a **POST** with `multipart/form-data`. The view parses and logs:

- `from`, `to`, `cc`, `subject`
- `text`, `html` (body)
- `envelope` (JSON string)
- `attachments` (count) and `attachment1`, `attachment2`, … (files)
- Other fields: `headers`, `charsets`, `SPF`, `dkim`, etc.

## Email parsing (DeepSeek)

Each received email is parsed with the DeepSeek API to extract:

- **Email title** (short description)
- **Buyer name**, **Buyer email**, **Buyer phone**
- **Listing ID**, **Time horizon**, **Amount to invest**, **Purchase timeframe**

Parsed data is stored on the same `InboundEmail` record and shown on the detail page (`/inbound/emails/<id>/`). The API key is read from the `DEEPSEEK_API_KEY` variable in your `.env` file.

Extend `process_inbound_email()` in `inbound/views.py` to implement your GHL automation (e.g. create tasks, update contacts).

## Signed NDA → GHL Contact

When a user saves a signed NDA (clicks "Next Req" in the NDA viewer):

1. The filled PDF is saved locally to `inbound/static/inbound/nda_signed/` (you can switch to S3 later)
2. The **link** to the PDF is saved to the contact's custom field in GHL (public URL: `NDA_PUBLIC_BASE_URL/static/inbound/nda_signed/<filename>.pdf`)
3. The tag **NDA_Signed** is added to the contact

**Setup:** In GHL, create a custom field for contacts (e.g. "Signed NDA") that can store a URL (Text or Website type). Get the field ID via `python manage.py list_ghl_custom_fields` and set `GHL_CUSTOM_FIELD_SIGNED_NDA` in `.env`. Set `NDA_PUBLIC_BASE_URL` to your public server URL (e.g. `http://50.16.97.238:8000` if Django runs on port 8000) so the PDF link is accessible. PDFs are served via `/inbound/nda/signed/<filename>`.

**Where to find the PDF in GHL:**
1. Go to **Contacts** (left sidebar) → click the contact
2. Scroll down to the **Custom Fields** section — the Signed NDA field contains the link to the PDF

**Verify:** Run `python manage.py verify_ghl_contact_fields <contact_id>`. If the Signed NDA field shows the URL, it succeeded.

## Security notes

- The webhook view uses `@csrf_exempt` because SendGrid does not send a CSRF token. In production, consider verifying requests with a shared secret or SendGrid’s verification options.
- Set `ALLOWED_HOSTS` and `SECRET_KEY` (e.g. via environment variables) for production.
- Use HTTPS for the webhook URL in SendGrid.
