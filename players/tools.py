"""Trade calculator, player comparison and the search API they use."""
from django.http import JsonResponse
from django.shortcuts import render
from .categories import TABS, TAB_BY_KEY
from .models import CategoryValue

METRICS = [
    ("Estimate", "total", "₹{:.1f} Cr"),
    ("Price before form", "base_value", "₹{:.1f} Cr"),
    ("Form effect", "form_premium", "{:+.1f} Cr"),
    ("Ability (percentile)", "quality_score", "{:.0f}%"),
    ("Consistency", "consistency_score", "{:.0f}/100"),
    ("Experience", "experience_score", "{:.0f}/100"),
    ("Potential", "potential_score", "{:.0f}/100"),
    ("Matches", "matches", "{:.0f}"),
]


def _cat(request):
    key = (request.GET.get("cat") or "T20").upper()
    return key if key in TAB_BY_KEY else "T20"


def _cv(cat, pid):
    if not (pid and str(pid).isdigit()):
        return None
    return (CategoryValue.objects.filter(player_id=int(pid), category=cat, group="")
            .select_related("player").first())


def _row(cv):
    p, total = cv.player, float(cv.total)
    return {"id": p.pk, "name": p.name,
            "country": "" if p.country in ("", "Unknown") else p.country,
            "role": p.get_role_display(), "total": round(total, 2),
            "low": round(cv.price_low or total, 2), "high": round(cv.price_high or total, 2),
            "matches": cv.matches, "last": cv.last_played.isoformat() if cv.last_played else ""}


def api_search(request):
    q, cat = (request.GET.get("q") or "").strip(), _cat(request)
    if len(q) < 2:
        return JsonResponse({"results": []})
    qs = (CategoryValue.objects.filter(category=cat, group="", player__name__icontains=q)
          .select_related("player")[:150])
    rows = sorted(qs, key=lambda c: c.total, reverse=True)[:12]
    return JsonResponse({"results": [_row(c) for c in rows]})


def compare(request):
    cat = _cat(request)
    a, b = _cv(cat, request.GET.get("a")), _cv(cat, request.GET.get("b"))
    rows = []
    if a and b:
        for label, attr, fmt in METRICS:
            va, vb = float(getattr(a, attr)), float(getattr(b, attr))
            rows.append({"label": label, "a": fmt.format(va), "b": fmt.format(vb),
                         "win": "a" if va > vb else "b" if vb > va else ""})
        rows.append({"label": "Last played", "a": str(a.last_played or "-"), "b": str(b.last_played or "-"), "win": ""})
        rows.append({"label": "Range", "a": f"₹{a.price_low:.1f}–{a.price_high:.1f} Cr",
                     "b": f"₹{b.price_low:.1f}–{b.price_high:.1f} Cr", "win": ""})
    return render(request, "players/compare.html", {
        "tabs": TABS, "current": "", "cat": cat, "cat_title": TAB_BY_KEY[cat]["title"],
        "all_tabs": TABS, "a": a, "b": b, "rows": rows})


def trade(request):
    cat = _cat(request)
    init = {}
    for side in ("a", "b"):
        ids = [int(i) for i in (request.GET.get(side) or "").split(",") if i.isdigit()][:12]
        found = {cv.player_id: cv for cv in CategoryValue.objects
                 .filter(category=cat, group="", player_id__in=ids).select_related("player")}
        init[side] = [_row(found[i]) for i in ids if i in found]
    return render(request, "players/trade.html", {
        "tabs": TABS, "current": "", "cat": cat, "cat_title": TAB_BY_KEY[cat]["title"],
        "all_tabs": TABS, "init": init})
