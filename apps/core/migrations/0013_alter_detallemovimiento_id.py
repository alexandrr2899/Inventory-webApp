from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0012_conteo_unique_activo'),
    ]

    operations = [
        migrations.AlterField(
            model_name='detallemovimiento',
            name='id',
            field=models.BigAutoField(
                auto_created=True,
                primary_key=True,
                serialize=False,
                verbose_name='ID',
            ),
        ),
    ]
