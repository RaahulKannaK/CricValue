# Copy to cricvalue/wsgi.py (gunicorn needs it).
import os
from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "cricvalue.settings")
application = get_wsgi_application()
