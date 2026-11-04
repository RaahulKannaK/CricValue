import datetime as dt
from django.core.management.base import BaseCommand
from players.models import Player, Match, Performance
from django.core.management import call_command

# SAMPLE data only, not real stats. (name, country, role, base Cr, [(runs, balls, wkts, conceded, overs)...] newest first)
DEMO = [
    ("Glenn Phillips", "New Zealand", "AR", 10, [(85, 48, 1, 24, 3), (64, 40, 0, 0, 0), (41, 30, 2, 28, 4)]),
    ("Azmatullah Omarzai", "Afghanistan", "AR", 6, [(110, 95, 2, 40, 8), (45, 50, 1, 35, 6), (30, 28, 3, 30, 5)]),
    ("Sikandar Raza", "Zimbabwe", "AR", 5.5, [(105, 80, 2, 30, 6), (52, 44, 1, 22, 4), (38, 36, 0, 18, 3)]),
    ("Rashid Khan", "Afghanistan", "BOWL", 12, [(8, 5, 3, 22, 4), (14, 9, 2, 25, 4), (0, 0, 1, 30, 4)]),
    ("Suryakumar Yadav", "India", "BAT", 15, [(44, 25, 0, 0, 0), (12, 14, 0, 0, 0), (58, 30, 0, 0, 0)]),
]

class Command(BaseCommand):
    help = "Load sample players and matches to try the site."
    def handle(self, *a, **o):
        today = dt.date.today()
        for name, country, role, base, perfs in DEMO:
            p, _ = Player.objects.get_or_create(name=name, country=country,
                                                defaults=dict(role=role, base_value=base))
            for i, (r, b, w, c, ov) in enumerate(perfs):
                m, _ = Match.objects.get_or_create(
                    external_id=f"demo-{name}-{i}",
                    defaults=dict(date=today - dt.timedelta(days=i * 4), competition="Demo T20",
                                  level="INTL", fmt="T20", category="T20", teams="India vs Australia"))
                Performance.objects.get_or_create(player=p, match=m, defaults=dict(
                    runs=r, balls=b, wickets=w, runs_conceded=c, overs=ov))
        call_command("recalc_values")
        self.stdout.write("Demo data loaded")
