from decimal import Decimal
from django.db import migrations, models
import django.db.models.deletion
from django.utils.text import slugify


def add_column_if_missing(apps, schema_editor, model_name, field_name, field):
    """Repair partially-applied MySQL migrations without duplicating columns."""
    Model = apps.get_model("players", model_name)
    table = Model._meta.db_table
    with schema_editor.connection.cursor() as cursor:
        existing = {c.name for c in schema_editor.connection.introspection.get_table_description(cursor, table)}
    if field_name not in existing:
        field.set_attributes_from_name(field_name)
        field.model = Model
        schema_editor.add_field(Model, field)


def add_player_dob(apps, schema_editor):
    add_column_if_missing(apps, schema_editor, "Player", "date_of_birth",
        models.DateField(blank=True, null=True, help_text="Optional verified date of birth; never inferred from match count."))


def add_player_potential_rating(apps, schema_editor):
    add_column_if_missing(apps, schema_editor, "Player", "potential_rating",
        models.FloatField(blank=True, null=True, help_text="Optional scouting input from 0-100. Leave blank to use a neutral evidence-based estimate."))


def add_category_potential_score(apps, schema_editor):
    add_column_if_missing(apps, schema_editor, "CategoryValue", "potential_score",
        models.FloatField(default=50, help_text="Potential / upside indicator, 0-100"))


def seed_markets(apps, schema_editor):
    Profile = apps.get_model("players", "AuctionMarketProfile")
    defaults = [
        ("IPL", "ipl", "IPL", "T20", "LEAGUE", "ipl", "120.00", 25, 10, 8, 1.08),
        ("International T20", "international-t20", "T20I", "T20", "T20", "", "100.00", 20, 10, None, 1.00),
        ("International ODI", "international-odi", "ODI", "ODI", "ODI", "", "100.00", 15, 10, None, 1.00),
        ("International Test", "international-test", "TEST", "TEST", "TEST", "", "100.00", 15, 10, None, 1.00),
        ("Domestic T20", "domestic-t20", "DOMESTIC", "T20", "DOM_T20", "", "100.00", 20, 10, None, 1.00),
        ("Domestic ODI", "domestic-odi", "DOMESTIC", "ODI", "DOM_ODI", "", "100.00", 20, 10, None, 1.00),
        ("Domestic Test / First Class", "domestic-test-first-class", "DOMESTIC", "TEST", "DOM_TEST", "", "100.00", 15, 10, None, 1.00),
    ]
    for name, slug, mtype, fmt, cat, group, purse, squad, teams, overseas, factor in defaults:
        Profile.objects.get_or_create(
            slug=slug,
            defaults={"name": name, "market_type": mtype, "cricket_format": fmt,
                      "source_category": cat, "source_group": group,
                      "team_purse": Decimal(purse), "squad_size": squad,
                      "team_count": teams, "overseas_limit": overseas,
                      "market_factor": factor, "is_active": True},
        )


def unseed_markets(apps, schema_editor):
    Profile = apps.get_model("players", "AuctionMarketProfile")
    Profile.objects.filter(slug__in=["ipl", "international-t20", "international-odi",
        "international-test", "domestic-t20", "domestic-odi",
        "domestic-test-first-class"]).delete()


class Migration(migrations.Migration):
    dependencies = [("players", "0008_match_lineups")]
    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[migrations.RunPython(add_player_dob, migrations.RunPython.noop)],
            state_operations=[migrations.AddField(model_name="player", name="date_of_birth",
                field=models.DateField(blank=True, help_text="Optional verified date of birth; never inferred from match count.", null=True))],
        ),
        migrations.SeparateDatabaseAndState(
            database_operations=[migrations.RunPython(add_player_potential_rating, migrations.RunPython.noop)],
            state_operations=[migrations.AddField(model_name="player", name="potential_rating",
                field=models.FloatField(blank=True, help_text="Optional scouting input from 0-100. Leave blank to use a neutral evidence-based estimate.", null=True))],
        ),
        migrations.SeparateDatabaseAndState(
            database_operations=[migrations.RunPython(add_category_potential_score, migrations.RunPython.noop)],
            state_operations=[migrations.AddField(model_name="categoryvalue", name="potential_score",
                field=models.FloatField(default=50, help_text="Potential / upside indicator, 0-100"))],
        ),
        migrations.CreateModel(name="AuctionMarketProfile", fields=[
            ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
            ("name", models.CharField(max_length=100, unique=True)),
            ("slug", models.SlugField(max_length=110, unique=True)),
            ("market_type", models.CharField(choices=[("IPL", "IPL-style league"), ("T20I", "International T20"), ("ODI", "International ODI"), ("TEST", "International Test"), ("DOMESTIC", "Domestic competition"), ("LEAGUE", "Other league"), ("CUSTOM", "Custom market")], default="CUSTOM", max_length=12)),
            ("cricket_format", models.CharField(choices=[("T20", "T20"), ("ODI", "ODI"), ("TEST", "Test")], default="T20", max_length=4)),
            ("source_category", models.CharField(blank=True, choices=[("T20", "T20"), ("ODI", "ODI"), ("TEST", "Test"), ("LEAGUE", "Leagues"), ("DOM_IN", "Domestic India")], default="", max_length=10)),
            ("source_group", models.CharField(blank=True, default="", help_text="Optional league/domestic group, e.g. ipl or bbl.", max_length=30)),
            ("team_purse", models.DecimalField(decimal_places=2, default=100, max_digits=9)),
            ("squad_size", models.PositiveSmallIntegerField(default=20)),
            ("team_count", models.PositiveSmallIntegerField(default=10)),
            ("overseas_limit", models.PositiveSmallIntegerField(blank=True, null=True)),
            ("market_factor", models.FloatField(default=1.0, help_text="Competition-level adjustment, normally 0.75-1.25.")),
            ("is_active", models.BooleanField(default=True)),
            ("created_at", models.DateTimeField(auto_now_add=True)),
            ("updated_at", models.DateTimeField(auto_now=True)),
        ], options={"ordering": ["name"]}),
        migrations.CreateModel(name="MarketValuation", fields=[
            ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
            ("global_base_value", models.DecimalField(decimal_places=2, default=0, max_digits=7)),
            ("market_adjustment", models.FloatField(default=1.0)),
            ("estimated_value", models.DecimalField(decimal_places=2, default=0, max_digits=7)),
            ("confidence_score", models.FloatField(default=0)),
            ("price_band", models.CharField(default="value", max_length=12)),
            ("explanation", models.JSONField(blank=True, default=dict)),
            ("calculated_at", models.DateTimeField(auto_now=True)),
            ("category_value", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="market_valuations", to="players.categoryvalue")),
            ("market", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="valuations", to="players.auctionmarketprofile")),
            ("player", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="market_valuations", to="players.player")),
        ], options={"ordering": ["-estimated_value", "player__name"], "unique_together": {("player", "market")}}),
        migrations.RunPython(seed_markets, unseed_markets),
    ]
