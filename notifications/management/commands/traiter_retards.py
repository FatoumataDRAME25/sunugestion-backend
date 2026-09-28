from django.core.management.base import BaseCommand
from django.utils import timezone

from cotisations.models import Cotisation
from prets.models import Pret
from notifications.service import envoyer_notification


class Command(BaseCommand):
    help = (
        "Détecte les cotisations et prêts en retard, "
        "met à jour leur statut et envoie une notification au membre concerné."
    )

    def handle(self, *args, **options):
        aujourd_hui = timezone.now().date()

        self._traiter_cotisations(aujourd_hui)
        self._traiter_prets(aujourd_hui)

    def _traiter_cotisations(self, aujourd_hui):
        """
        Passe en 'en_retard' les cotisations dont la session est terminée
        et envoie une notification au membre concerné.
        Seules les cotisations encore 'en_cours' sont traitées — pas de double notification.
        """
        cotisations_en_retard = Cotisation.objects.filter(
            statut='en_cours',
            session__date_fin__lt=aujourd_hui,
        ).select_related('membre', 'session')

        total = cotisations_en_retard.count()

        if total == 0:
            self.stdout.write("Cotisations : aucun retard détecté.")
            return

        nb_traites = 0

        for cotisation in cotisations_en_retard:
            cotisation.statut = 'en_retard'
            cotisation.save(update_fields=['statut'])

            envoyer_notification(
                destinataires=[cotisation.membre],
                titre="Cotisation en retard",
                message=(
                    f"Votre cotisation pour la session "
                    f"« {cotisation.session.libelle} » est en retard. "
                    f"Veuillez régulariser votre situation."
                ),
                type_evenement="cotisation_en_retard",
                module="cotisations",
                objet_id=cotisation.id,
            )

            nb_traites += 1

        self.stdout.write(
            self.style.WARNING(
                f"Cotisations : {nb_traites} retard(s) traité(s) sur {total}."
            )
        )

    def _traiter_prets(self, aujourd_hui):
        """
        Passe en 'en_retard' les prêts dont la date d'échéance est dépassée
        et envoie une notification à l'emprunteur.
        Seuls les prêts encore 'en_cours' sont traités — pas de double notification.
        """
        prets_en_retard = Pret.objects.filter(
            statut='en_cours',
            date_echeance__lt=aujourd_hui,
        ).select_related('membre')

        total = prets_en_retard.count()

        if total == 0:
            self.stdout.write("Prêts : aucun retard détecté.")
            return

        nb_traites = 0

        for pret in prets_en_retard:
            pret.statut = 'en_retard'
            pret.save(update_fields=['statut'])

            envoyer_notification(
                destinataires=[pret.membre],
                titre="Prêt en retard",
                message=(
                    f"Votre prêt de {pret.montant} FCFA est en retard. "
                    f"La date d'échéance était le {pret.date_echeance}. "
                    f"Veuillez procéder au remboursement."
                ),
                type_evenement="pret_en_retard",
                module="prets",
                objet_id=pret.id,
            )

            nb_traites += 1

        self.stdout.write(
            self.style.WARNING(
                f"Prêts : {nb_traites} retard(s) traité(s) sur {total}."
            )
        )
