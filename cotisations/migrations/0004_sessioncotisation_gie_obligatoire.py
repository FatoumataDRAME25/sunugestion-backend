import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('cotisations', '0003_sessioncotisation_gie'),
    ]

    operations = [
        migrations.AlterField(
            model_name='sessioncotisation',
            name='gie',
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name='sessions_cotisation',
                to='authentication.gie',
            ),
        ),
    ]
