"""
URL configuration for ghl_automation project.
"""
from django.contrib import admin
from django.urls import path, include
from django.views.generic import RedirectView

from inbound.views import sendgrid_inbound

urlpatterns = [
    path('', RedirectView.as_view(url='/inbound/nda/contacts/', permanent=False)),
    path('admin/', admin.site.urls),
    path('inbound/', include('inbound.urls')),
    # SendGrid Inbound Parse: support both URL styles
    path('sendgrid/webhook/inbound/', sendgrid_inbound),
]
