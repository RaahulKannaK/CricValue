from django.db import migrations, models


def split_legacy_domestic_category(apps, schema_editor):
    Match = apps.get_model("players", "Match")
    # Split domestic match records by format. Existing aggregate DOM_IN valuations are retained
    # as legacy data; recalc_values rebuilds the new format-specific CategoryValue rows.
    for fmt, category in (("T20", "DOM_T20"), ("ODI", "DOM_ODI"), ("TEST", "DOM_TEST")):
        Match.objects.filter(category="DOM_IN", fmt=fmt).update(category=category)
    # Profiles created by migration 0009 get their matching format-specific source tab.
    Profile = apps.get_model("players", "AuctionMarketProfile")
    for fmt, category in (("T20", "DOM_T20"), ("ODI", "DOM_ODI"), ("TEST", "DOM_TEST")):
        Profile.objects.filter(market_type="DOMESTIC", cricket_format=fmt).update(source_category=category)


class Migration(migrations.Migration):
    dependencies = [("players", "0009_market_profiles_and_potential")]
    operations = [
        migrations.AlterField(model_name="match", name="category", field=models.CharField(blank=True, db_index=True, default="", max_length=10)),
        migrations.AlterField(model_name="categoryvalue", name="category", field=models.CharField(choices=[("T20", "T20"), ("ODI", "ODI"), ("TEST", "Test"), ("LEAGUE", "Leagues"), ("DOM_T20", "Domestic T20"), ("DOM_ODI", "Domestic ODI"), ("DOM_TEST", "Domestic First Class"), ("DOM_IN", "Domestic India (legacy)")], db_index=True, max_length=10)),
        migrations.AlterField(model_name="auctionmarketprofile", name="source_category", field=models.CharField(blank=True, choices=[("T20", "T20"), ("ODI", "ODI"), ("TEST", "Test"), ("LEAGUE", "Leagues"), ("DOM_T20", "Domestic T20"), ("DOM_ODI", "Domestic ODI"), ("DOM_TEST", "Domestic First Class"), ("DOM_IN", "Domestic India (legacy)")], default="", max_length=10)),
        migrations.RunPython(split_legacy_domestic_category, migrations.RunPython.noop),
    ]
