from django.core.management.base import BaseCommand
from players.models import Match
from players.categories import category_of


class Command(BaseCommand):
    help = "Set the tab category on matches already in the database."

    def handle(self, *a, **o):
        ms = list(Match.objects.all())
        for m in ms:
            m.category = category_of(m.level, m.fmt, m.competition) or ""
        Match.objects.bulk_update(ms, ["category"], batch_size=500)
        self.stdout.write(f"Updated {len(ms)} matches")