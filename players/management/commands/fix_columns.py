"""Add any missing new columns to the database (and report unexpected ones).

Use this when 'migrate' fails with 'Duplicate column name', then run:
    python manage.py migrate players 0009 --fake
"""
from django.apps import apps
from django.core.management.base import BaseCommand
from django.db import connection

SPEC = {
    "players_player": [
        ("dob", "date NULL"),
        ("market_demand", "double precision NOT NULL DEFAULT 1"),
        ("role_locked", "bool NOT NULL DEFAULT 0"),
    ],
    "players_categoryvalue": [
        ("market_score", "double precision NOT NULL DEFAULT 0"),
        ("price_mult", "double precision NOT NULL DEFAULT 1"),
        ("form_reliability", "double precision NOT NULL DEFAULT 1"),
        ("potential_score", "double precision NOT NULL DEFAULT 0"),
        ("potential_source", "varchar(8) NOT NULL DEFAULT ''"),
        ("experience_score", "double precision NOT NULL DEFAULT 0"),
        ("price_low", "double precision NOT NULL DEFAULT 0"),
        ("price_high", "double precision NOT NULL DEFAULT 0"),
    ],
}
MODELS = {"players_player": "Player", "players_categoryvalue": "CategoryValue"}


class Command(BaseCommand):
    help = __doc__

    def handle(self, *a, **o):
        with connection.cursor() as cur:
            for table, columns in SPEC.items():
                desc = {c.name: c for c in connection.introspection.get_table_description(cur, table)}
                for name, ddl in columns:
                    if name in desc:
                        self.stdout.write(f"{table}.{name}: already exists")
                    else:
                        cur.execute(f"ALTER TABLE `{table}` ADD COLUMN `{name}` {ddl}")
                        self.stdout.write(self.style.SUCCESS(f"{table}.{name}: added"))
                model = apps.get_model("players", MODELS[table])
                known = {f.column for f in model._meta.concrete_fields}
                extra = sorted(set(desc) - known)
                if extra:
                    self.stdout.write(self.style.WARNING(
                        f"{table}: columns in the database that this version does not use: {', '.join(extra)}"))
                if "dob" in desc and not desc["dob"].null_ok:
                    self.stdout.write(self.style.WARNING("players_player.dob does not allow empty values"))