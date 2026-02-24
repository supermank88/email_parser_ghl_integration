"""
URL configuration for ghl_automation project.
"""
from django.contrib import admin
from django.urls import path, include

from inbound.views import sendgrid_inbound

urlpatterns = [
    path('admin/', admin.site.urls),
    path('inbound/', include('inbound.urls')),
    # SendGrid Inbound Parse: support both URL styles
    path('sendgrid/webhook/inbound/', sendgrid_inbound),
]
