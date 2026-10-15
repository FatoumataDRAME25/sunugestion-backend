from datetime import timedelta

from django.db import migrations
from django.utils import timezone


def donner_une_expiration_aux_invitations(apps, schema_editor):
    """
    Les invitations créées avant l'introduction de l'expiration n'ont pas de
    date limite. Leur délai de 72 heures démarre à l'application de cette
    migration : aucun compte en attente n'est supprimé sans préavis.
    """
    Utilisateur = apps.get_model('authentication', 'Utilisateur')

    Utilisateur.objects.filter(
        statut='en_attente',
        token_invitation__isnull=False,
        token_expiration__isnull=True,
    ).update(token_expiration=timezone.now() + timedelta(hours=72))


class Migration(migrations.Migration):

    dependencies = [
        ('authentication', '0007_utilisateur_fonction_bureau'),
    ]

    operations = [
        migrations.RunPython(
            donner_une_expiration_aux_invitations,
            migrations.RunPython.noop,
        ),
    ]
