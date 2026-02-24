from django.db import models


class InboundEmail(models.Model):
    """Stores emails received via SendGrid Inbound Parse webhook."""
    from_address = models.CharField(max_length=512)
    to_address = models.TextField(blank=True)
    cc = models.TextField(blank=True)
    subject = models.CharField(max_length=1024, blank=True)
    text_body = models.TextField(blank=True)
    html_body = models.TextField(blank=True)
    envelope = models.JSONField(default=dict, blank=True)
    attachment_info = models.JSONField(default=list, blank=True)  # names, sizes, types
    received_at = models.DateTimeField(auto_now_add=True)

    # From headers (for dedupe)
    original_email_message_id = models.CharField(max_length=512, blank=True)  # Message-ID

    # Parsed fields (DeepSeek) – lead extraction
    lead_source = models.CharField(max_length=128, blank=True)  # BizBuySell / TangentBrokerage.com / BusinessesforSale.com
    listing_id = models.CharField(max_length=255, blank=True)
    listing_name = models.CharField(max_length=512, blank=True)
    listing_profit = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True)  # number
    name = models.CharField(max_length=255, blank=True)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=64, blank=True)
    purchase_timeframe = models.CharField(max_length=255, blank=True)
    amount_to_invest = models.CharField(max_length=255, blank=True)
    lead_message = models.TextField(blank=True)
    ref_id = models.CharField(max_length=128, blank=True)  # Your Ref ID#
    email_title = models.CharField(max_length=512, blank=True)  # same as subject
    time_horizon = models.CharField(max_length=255, blank=True)  # legacy
    parsed_at = models.DateTimeField(null=True, blank=True)
    raw_parsed = models.JSONField(default=dict, blank=True)

    # GHL integration
    ghl_contact_id = models.CharField(max_length=64, blank=True)

    class Meta:
        ordering = ['-received_at']
        verbose_name = 'Inbound Email'
        verbose_name_plural = 'Inbound Emails'

    def __str__(self):
        return self.subject or '(no subject)'
