import json
from django.conf import settings
from django.db.models import Max
from .models import Match


def site_status(request):
    """Footer info: newest match in the database and when the daily job last ran."""
    info = {}
    try:
        info = json.loads((settings.BASE_DIR / "data" / "last_update.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    return {"site_status": {
        "latest_match": Match.objects.aggregate(m=Max("date"))["m"],
        "ran_at": (info.get("ran_at") or "").replace("T", " ")[:16],
        "ok": info.get("ok"),
    }}
