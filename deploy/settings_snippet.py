"""Paste the relevant parts into your Django settings.py (I have not seen your settings file).

requirements.txt needs:  gunicorn, whitenoise, boto3, requests, and your MySQL driver
(mysqlclient or PyMySQL). django-storages is NOT needed: the app reads B2 directly.

Render settings:
  Build command:  pip install -r requirements.txt && python manage.py collectstatic --noinput && python manage.py migrate --noinput
  Start command:  gunicorn <your_project>.wsgi:application     (the folder that holds your settings.py)
Render environment variables: SECRET_KEY, DEBUG=False, ALLOWED_HOSTS, DB_NAME, DB_USER,
  DB_PASSWORD, DB_HOST, DB_PORT, B2_KEY_ID, B2_APP_KEY, B2_BUCKET, B2_ENDPOINT, B2_REGION
"""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.environ["SECRET_KEY"]
DEBUG = os.environ.get("DEBUG", "False") == "True"
ALLOWED_HOSTS = [h for h in os.environ.get("ALLOWED_HOSTS", "").split(",") if h]
CSRF_TRUSTED_ORIGINS = [f"https://{h}" for h in ALLOWED_HOSTS if not h.startswith(".")]

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.mysql",
        "NAME": os.environ["DB_NAME"],
        "USER": os.environ["DB_USER"],
        "PASSWORD": os.environ["DB_PASSWORD"],
        "HOST": os.environ["DB_HOST"],
        "PORT": os.environ["DB_PORT"],
        "CONN_MAX_AGE": 60,
        # Aiven only accepts SSL connections. "ssl_mode" works with mysqlclient;
        # with PyMySQL use  "ssl": {"ca": "/path/to/aiven-ca.pem"}  instead.
        "OPTIONS": {"ssl_mode": "REQUIRED", "charset": "utf8mb4"},
    }
}

# Static files on Render (site.css): WhiteNoise serves them.
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",   # directly after SecurityMiddleware
    # ... your other middleware ...
]
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedStaticFilesStorage"},
}
