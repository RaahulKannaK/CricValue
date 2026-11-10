from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("players", "0006_dynamic_strength")]
    operations = [
        migrations.AddField(model_name="categoryvalue", name="quality_score", field=models.FloatField(default=0, help_text="Long-term player quality, 0-100")),
        migrations.AddField(model_name="categoryvalue", name="consistency_score", field=models.FloatField(default=0, help_text="Consistency indicator, 0-100")),
        migrations.AddField(model_name="categoryvalue", name="confidence_score", field=models.FloatField(default=0, help_text="Confidence in this estimate, 0-100")),
        migrations.AddField(model_name="categoryvalue", name="price_band", field=models.CharField(db_index=True, default="unrated", max_length=12)),
    ]
