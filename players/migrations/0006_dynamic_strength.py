from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("players", "0005_categoryvalue_tier"),
    ]

    operations = [
        migrations.AddField(model_name="performance", name="opp_strength",
                            field=models.FloatField(default=1.0)),
        migrations.AddField(model_name="categoryvalue", name="rating",
                            field=models.FloatField(default=0)),
        migrations.AddField(model_name="categoryvalue", name="ceiling",
                            field=models.FloatField(default=25)),
    ]
