from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("players", "0003_alter_categoryvalue_unique_together_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="match",
            name="strength",
            field=models.FloatField(default=1.0),
        ),
        migrations.AddField(
            model_name="match",
            name="teams",
            field=models.CharField(blank=True, default="", max_length=160),
        ),
    ]
