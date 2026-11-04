from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("players", "0004_match_strength_match_teams"),
    ]

    operations = [
        migrations.AddField(
            model_name="categoryvalue",
            name="tier",
            field=models.CharField(blank=True, db_index=True, default="", max_length=10),
        ),
    ]
