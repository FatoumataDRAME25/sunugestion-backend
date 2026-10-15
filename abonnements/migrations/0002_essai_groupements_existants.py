from datetime import timedelta

from django.db import migrations
from django.utils import timezone


def ouvrir_un_essai_pour_les_groupements_existants(apps, schema_editor):
    """
    Les groupements créés avant les abonnements reçoivent un essai gratuit
    de 30 jours à partir de la mise en place : personne n'est bloqué du jour
    au lendemain.
    """
    GIE = apps.get_model('authentication', 'GIE')
    Abonnement = apps.get_model('abonnements', 'Abonnement')

    aujourd_hui = timezone.localdate()
    deja = set(Abonnement.objects.values_list('gie_id', flat=True))

    Abonnement.objects.bulk_create([
        Abonnement(
            gie_id=gie_id,
            statut='essai',
            date_debut=aujourd_hui,
            date_fin=aujourd_hui + timedelta(days=29),
        )
        for gie_id in GIE.objects.exclude(id__in=deja).values_list('id', flat=True)
    ])


class Migration(migrations.Migration):

    dependencies = [
        ('abonnements', '0001_initial'),
        ('authentication', '0008_expiration_invitations_existantes'),
    ]

    operations = [
        migrations.RunPython(
            ouvrir_un_essai_pour_les_groupements_existants,
            migrations.RunPython.noop,
        ),
    ]
