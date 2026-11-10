import json
from django.conf import settings
from django.core.cache import cache
from django.db.models import Max
from .models import Match


def _import_status():
    """When the daily job last ran. Read from the B2 bucket (cached 15 minutes), because
    the web server's own disk is wiped on every deploy; falls back to the old local file."""
    info = cache.get("import_status")
    if info is not None:
        return info
    info, ttl = {}, 900
    try:
        from . import storage_b2
        if storage_b2.configured():
            info = storage_b2.get_json("metadata/import_status.json", {}) or {}
        else:
            info = json.loads((settings.BASE_DIR / "data" / "last_update.json").read_text(encoding="utf-8"))
    except Exception:
        info, ttl = {}, 60          # footer info is optional; never break a page over it
    cache.set("import_status", info, ttl)
    return info


def site_status(request):
    """Footer info: newest match in the database and when the daily job last ran."""
    info = _import_status()
    return {"site_status": {
        "latest_match": Match.objects.aggregate(m=Max("date"))["m"],
        "ran_at": (info.get("ran_at") or "").replace("T", " ")[:16],
        "ok": info.get("ok"),
    }}
