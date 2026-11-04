from django.core.management.base import BaseCommand
from players.market_valuation import recalculate_all_markets


class Command(BaseCommand):
    help = "Recalculate player auction estimates for every active market profile."

    def handle(self, *args, **options):
        results = recalculate_all_markets()
        total = sum(results.values())
        for market, count in results.items():
            self.stdout.write(f"  {market}: {count} player valuations")
        self.stdout.write(self.style.SUCCESS(
            f"Recalculated {total} market valuations across {len(results)} active markets."
        ))
