"""Imports one parsed Cricsheet match into the database.

Same rules as the original import_cricsheet command, but players are cached in
memory and a match's performances are written with one bulk insert. That matters
when the database is remote (Aiven): a full import would otherwise run several
queries per player per match.
"""
from django.db import IntegrityError, transaction
from django.utils import timezone

from players.categories import category_of
from players.cricsheet import parse_match
from players.models import Match, Performance, Player
from players.strength import strength_of


class MatchImporter:
    def __init__(self, women=False):
        self.women = women
        self._load()

    def _load(self):
        self.by_cid, self.by_name, self.country = {}, {}, {}
        for pk, name, country, cid in Player.objects.values_list(
                "pk", "name", "country", "cricsheet_id"):
            self.country[pk] = country
            self.by_name.setdefault((name, country), pk)
            if cid:
                self.by_cid[cid] = pk

    def _find(self, cid, name, country):
        pk = self.by_cid.get(cid) if cid else None
        return pk if pk is not None else self.by_name.get((name, country))

    def _create(self, name, cid, country):
        pl = Player.objects.create(
            name=name, cricsheet_id=cid or None, country=country, role="BAT")
        self.country[pl.pk] = country
        self.by_name.setdefault((name, country), pl.pk)
        if cid:
            self.by_cid[cid] = pl.pk
        return pl.pk

    def _set_country(self, pk, country, name):
        if self.country.get(pk) == country:
            return
        Player.objects.filter(pk=pk).update(country=country, updated=timezone.now())
        self.country[pk] = country
        self.by_name.setdefault((name, country), pk)

    def import_one(self, ext, data):
        """Returns "new" or "skipped"; safe against repeated/concurrent imports."""
        ext = str(ext or "").strip()
        if not ext or Match.objects.filter(external_id=ext).exists():
            return "skipped"
        m = parse_match(data, self.women)
        if not m or not m["date"]:
            return "skipped"
        cat = category_of(m["level"], m["fmt"], m["competition"]) or ""
        intl = m["level"] == "INTL"
        try:
            with transaction.atomic():
                lineup_ids = {}
                for team, selected in (m.get("lineups") or {}).items():
                    ids = []
                    for entry in selected:
                        cid, name = entry.get("cid") or "", entry["name"]
                        pk = self._find(cid, name, team)
                        if pk is None:
                            pk = self._create(name, cid, team if intl else "Unknown")
                        elif intl:
                            self._set_country(pk, team, name)
                        ids.append(pk)
                    lineup_ids[team] = ids

                match = Match.objects.create(
                    date=m["date"], competition=m["competition"][:80], level=m["level"],
                    fmt=m["fmt"], external_id=ext, category=cat,
                    teams=" vs ".join(m["teams"])[:160], lineups=lineup_ids,
                    strength=strength_of(cat, m["competition"], m["teams"]))

                rows = {}
                for r in m["players"]:
                    country = r["country"] or "Unknown"
                    pk = self._find(r["cid"], r["name"], country)
                    if pk is None:
                        pk = self._create(r["name"], r["cid"], country)
                    elif r["country"]:
                        self._set_country(pk, r["country"], r["name"])
                    rows[pk] = Performance(
                        player_id=pk, match=match, runs=r["runs"], balls=r["balls"],
                        wickets=r["wickets"], runs_conceded=r["conceded"],
                        overs=r["overs"], phases=r.get("phases") or {})
                Performance.objects.bulk_create(rows.values(), batch_size=500)
        except IntegrityError:
            # A concurrent worker may have inserted this external ID after the
            # initial existence check. The unique DB constraint is authoritative.
            self._load()
            if Match.objects.filter(external_id=ext).exists():
                return "skipped"
            raise
        except Exception:
            self._load()      # the rolled-back transaction may have left stale cache entries
            raise
        return "new"
