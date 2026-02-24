"""
Django settings for ghl_automation project.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / '.env')

SECRET_KEY = os.environ.get(
    'DJANGO_SECRET_KEY',
    'django-insecure-change-me-in-production'
)

DEBUG = os.environ.get('DJANGO_DEBUG', 'True').lower() in ('1', 'true', 'yes')

ALLOWED_HOSTS = os.environ.get('ALLOWED_HOSTS', 'localhost,127.0.0.1,50.16.97.238').split(',')

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'inbound',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'ghl_automation.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'ghl_automation.wsgi.application'

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db.sqlite3',
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_TZ = True

STATIC_URL = '/static/'
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# DeepSeek API (for email parsing); set in .env as DEEPSEEK_API_KEY
DEEPSEEK_API_KEY = os.environ.get('DEEPSEEK_API_KEY', '')

# GoHighLevel (GHL) – contact mapping; all keys in .env
GHL_API_KEY = os.environ.get('GHL_API_KEY', '')
GHL_LOCATION_ID = os.environ.get('GHL_LOCATION_ID', '')
# Optional: GHL custom field IDs (get from Location → Custom Fields in GHL)
GHL_CUSTOM_FIELD_LISTING_ID = os.environ.get('GHL_CUSTOM_FIELD_LISTING_ID', '')
GHL_CUSTOM_FIELD_LISTING_NAME = os.environ.get('GHL_CUSTOM_FIELD_LISTING_NAME', '')
GHL_CUSTOM_FIELD_REF_ID = os.environ.get('GHL_CUSTOM_FIELD_REF_ID', '')
GHL_CUSTOM_FIELD_LEAD_SOURCE = os.environ.get('GHL_CUSTOM_FIELD_LEAD_SOURCE', '')
GHL_CUSTOM_FIELD_PURCHASE_TIMEFRAME = os.environ.get('GHL_CUSTOM_FIELD_PURCHASE_TIMEFRAME', '')
GHL_CUSTOM_FIELD_AMOUNT_TO_INVEST = os.environ.get('GHL_CUSTOM_FIELD_AMOUNT_TO_INVEST', '')
GHL_CUSTOM_FIELD_LEAD_MESSAGE = os.environ.get('GHL_CUSTOM_FIELD_LEAD_MESSAGE', '')

# Allow larger inbound parse payloads (SendGrid "Send Raw" / big emails + attachments)
# Increase if you receive very large emails (e.g. 25 * 1024 * 1024 for 25 MB)
DATA_UPLOAD_MAX_MEMORY_SIZE = 25 * 1024 * 1024  # 25 MB
FILE_UPLOAD_MAX_MEMORY_SIZE = 25 * 1024 * 1024  # 25 MB
