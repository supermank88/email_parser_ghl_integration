from django.contrib import admin
from .models import InboundEmail


@admin.register(InboundEmail)
class InboundEmailAdmin(admin.ModelAdmin):
    list_display = ('subject', 'lead_source', 'from_address', 'name', 'listing_id', 'ghl_contact_id', 'received_at')
    list_filter = ('received_at', 'lead_source')
    search_fields = (
        'from_address', 'to_address', 'subject', 'text_body', 'name', 'email',
        'listing_id', 'listing_name', 'ref_id', 'original_email_message_id',
    )
    readonly_fields = (
        'from_address', 'to_address', 'cc', 'subject', 'text_body', 'html_body',
        'envelope', 'attachment_info', 'received_at', 'original_email_message_id',
        'lead_source', 'listing_id', 'listing_name', 'listing_profit',
        'name', 'email', 'phone', 'purchase_timeframe', 'amount_to_invest',
        'lead_message', 'ref_id', 'email_title', 'time_horizon',
        'parsed_at', 'raw_parsed', 'ghl_contact_id',
    )
