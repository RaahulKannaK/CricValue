from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("players", "0007_quality_and_price_band")]

    operations = [
        migrations.AddField(
            model_name="match",
            name="lineups",
            field=models.JSONField(blank=True, default=dict),
        ),
    ]
