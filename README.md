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

- **Local:** `http://localhost:8000/inbound/webhook/sendgrid/`
- **Production:** `https://your-domain.com/inbound/webhook/sendgrid/`

For local testing with SendGrid, use a tunnel (e.g. [ngrok](https://ngrok.com/)) so SendGrid can reach your machine.

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

## Security notes

- The webhook view uses `@csrf_exempt` because SendGrid does not send a CSRF token. In production, consider verifying requests with a shared secret or SendGrid’s verification options.
- Set `ALLOWED_HOSTS` and `SECRET_KEY` (e.g. via environment variables) for production.
- Use HTTPS for the webhook URL in SendGrid.
