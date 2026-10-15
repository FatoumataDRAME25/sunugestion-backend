import logging

from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models.deletion import ProtectedError
from django.utils import timezone

from authentication.models import Utilisateur
from notifications.service import envoyer_notification

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = (
        "Supprime les comptes en attente dont le lien d'invitation a expiré "
        "et prévient le président de leur groupement."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--simulation',
            action='store_true',
            help="Affiche les comptes concernés sans rien supprimer.",
        )

    def handle(self, *args, **options):
        maintenant = timezone.now()

        # Uniquement des comptes jamais activés : un compte actif ou suspendu
        # n'est jamais concerné.
        expires = Utilisateur.objects.filter(
            statut='en_attente',
            token_expiration__isnull=False,
            token_expiration__lte=maintenant,
        ).select_related('gie')

        total = expires.count()

        if total == 0:
            self.stdout.write("Invitations : aucun compte expiré.")
            return

        if options['simulation']:
            for membre in expires:
                self.stdout.write(
                    f"[simulation] {membre.prenom} {membre.nom} "
                    f"({membre.telephone}) — GIE {membre.gie_id}"
                )
            self.stdout.write(f"Invitations : {total} compte(s) seraient supprimé(s).")
            return

        supprimes = 0

        for membre in expires:
            gie = membre.gie
            nom_complet = f"{membre.prenom} {membre.nom}"

            try:
                with transaction.atomic():
                    membre.delete()
            except ProtectedError:
                # Données liées inattendues : le compte est conservé
                logger.warning(
                    "Invitation expirée non supprimée (données liées) : utilisateur %s",
                    membre.id,
                )
                continue

            supprimes += 1

            if gie is not None:
                presidents = Utilisateur.objects.filter(
                    gie=gie, role='president', statut='actif'
                )
                if presidents.exists():
                    envoyer_notification(
                        destinataires=presidents,
                        titre="Invitation expirée",
                        message=(
                            f"Le compte en attente de {nom_complet} a été supprimé : "
                            f"l'invitation n'a pas été activée sous 72 heures. "
                            f"Vous pouvez l'ajouter à nouveau si nécessaire."
                        ),
                        type_evenement='invitation_expiree',
                        module='membres',
                    )

        self.stdout.write(
            self.style.SUCCESS(
                f"Invitations : {supprimes} compte(s) supprimé(s) sur {total}."
            )
        )
