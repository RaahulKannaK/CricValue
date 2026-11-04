from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("players", "0010_format_specific_domestic_categories")]
    operations = [
        migrations.AddField(
            model_name="performance", name="phases",
            field=models.JSONField(blank=True, default=dict),
        ),
    ]
