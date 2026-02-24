"""
ASGI config for ghl_automation project.
"""

import os

from django.core.asgi import get_asgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'ghl_automation.settings')

application = get_asgi_application()
