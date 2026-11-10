from django.core.management.base import BaseCommand, CommandError
from players.categories import TAB_BY_KEY
from players.models import Player
from players.valuation import impact, raw_impact


class Command(BaseCommand):
    help = 'Show step by step how a player\'s tier, form and price were reached. Example: debug_player "Evans"'

    def add_arguments(self, parser):
        parser.add_argument("name")
        parser.add_argument("--cat", default="", help="T20, ODI, TEST, LEAGUE or DOM_IN (default: all)")
        parser.add_argument("--n", type=int, default=10, help="matches to show")

    def handle(self, *a, **o):
        found = list(Player.objects.filter(name__icontains=o["name"])[:8])
        if not found:
            raise CommandError("No player matches that name")
        for p in found:
            self.stdout.write(f"\n=== {p.name} ({p.country}) id={p.pk} role={p.role}")
            vals = p.cat_values.filter(group="")
            if o["cat"]:
                vals = vals.filter(category=o["cat"].upper())
            for v in vals.order_by("category"):
                self.stdout.write(
                    f"\n[{TAB_BY_KEY[v.category]['title']}] tier={v.tier or '-'}  rating={v.rating}  "
                    f"matches={v.matches}  last played={v.last_played}\n"
                    f"  base price (tier band, scaled by nation) = {v.base_value} Cr\n"
                    f"  form = {v.form_score:+.1f}%  ->  moves price by {v.form_premium:+} Cr "
                    f"(ceiling at best form = {v.ceiling} Cr)\n"
                    f"  FINAL PRICE = {v.total} Cr")
                self.stdout.write("  date        match                                   bat      bowl      raw  x opp  = impact")
                perfs = [f for f in p.performances.select_related("match").order_by("-match__date")
                         if f.match.category == v.category][: o["n"]]
                for f in perfs:
                    fac = f.opp_strength if v.category in ("T20", "ODI", "TEST") else f.match.strength
                    self.stdout.write(
                        f"  {f.match.date}  {(f.match.teams or f.match.competition)[:38]:38}  "
                        f"{f.runs:>3}({f.balls:>2})  {f.wickets}/{f.runs_conceded:<3} {f.overs:>4}ov  "
                        f"{raw_impact(f):5.1f}  x{fac:4.2f}  = {impact(f):5.1f}")
