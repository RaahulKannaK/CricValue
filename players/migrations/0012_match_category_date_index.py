from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("players", "0011_performance_phases")]

    operations = [
        migrations.AddIndex(
            model_name="match",
            index=models.Index(fields=["category", "date"], name="match_cat_date_idx"),
        ),
    ]
