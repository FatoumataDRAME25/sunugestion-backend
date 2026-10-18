# Rattache chaque session directement à son groupement. Le champ est d'abord
# facultatif, puis rempli d'après le groupement du créateur ; il devient
# obligatoire dans la migration suivante (séparée : PostgreSQL refuse de
# modifier une colonne après une mise à jour de clé étrangère dans la même
# transaction).

import django.db.models.deletion
from django.db import migrations, models


def remplir_gie(apps, schema_editor):
    SessionCotisation = apps.get_model('cotisations', 'SessionCotisation')
    sessions = list(SessionCotisation.objects.select_related('createur'))
    sans_groupement = [s.id for s in sessions if s.createur.gie_id is None]
    if sans_groupement:
        raise RuntimeError(
            f"Sessions dont le créateur n'a pas de groupement : {sans_groupement}. "
            "Leur attribuer un groupement avant de relancer la migration."
        )
    for session in sessions:
        session.gie_id = session.createur.gie_id
    SessionCotisation.objects.bulk_update(sessions, ['gie'])


class Migration(migrations.Migration):

    dependencies = [
        ('authentication', '0009_renommer_photo_en_logo'),
        ('cotisations', '0002_cotisation_token_paydunya'),
    ]

    operations = [
        migrations.AddField(
            model_name='sessioncotisation',
            name='gie',
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name='sessions_cotisation',
                to='authentication.gie',
            ),
        ),
        migrations.RunPython(remplir_gie, migrations.RunPython.noop),
    ]
