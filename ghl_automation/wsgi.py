"""
WSGI config for ghl_automation project.
"""

import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'ghl_automation.settings')

application = get_wsgi_application()
