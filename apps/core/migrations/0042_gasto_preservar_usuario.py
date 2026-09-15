import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('core', '0041_contabilidad'),
    ]

    operations = [
        migrations.AlterField(
            model_name='gasto',
            name='registrado_por',
            field=models.ForeignKey(
                editable=False,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name='gastos_registrados',
                to=settings.AUTH_USER_MODEL,
            ),
        ),
    ]
