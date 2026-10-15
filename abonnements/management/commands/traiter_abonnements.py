from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from authentication.models import GIE, Utilisateur
from notifications.service import envoyer_notification

from abonnements.services import calculer_tarif, compter_membres_actifs, obtenir_abonnement


class Command(BaseCommand):
    help = (
        "Envoie les rappels d'abonnement au président et au trésorier : "
        "7 jours avant l'échéance, la veille, le jour même, au début du délai "
        "de grâce et au passage en lecture seule."
    )

    def handle(self, *args, **options):
        aujourd_hui = timezone.localdate()
        envoyes = 0

        for gie in GIE.objects.filter(statut='actif'):
            abonnement = obtenir_abonnement(gie)
            message = self._message(abonnement, gie, aujourd_hui)
            if not message:
                continue

            destinataires = Utilisateur.objects.filter(
                gie=gie, role__in=['president', 'tresorier'], statut='actif'
            )
            if not destinataires.exists():
                continue

            titre, texte = message
            envoyer_notification(
                destinataires=destinataires,
                titre=titre,
                message=texte,
                type_evenement='rappel_abonnement',
                module='general',
            )
            envoyes += 1

        self.stdout.write(f"Abonnements : {envoyes} rappel(s) envoyé(s).")

    def _message(self, abonnement, gie, aujourd_hui):
        fin = abonnement.date_fin.strftime('%d/%m/%Y')
        montant = calculer_tarif(compter_membres_actifs(gie))['montant']
        nature = "Votre essai gratuit" if abonnement.statut == 'essai' else "Votre abonnement"
        jours = (abonnement.date_fin - aujourd_hui).days

        if jours in (7, 1, 0):
            quand = {7: "dans 7 jours", 1: "demain", 0: "aujourd'hui"}[jours]
            return (
                "Abonnement : échéance proche",
                f"{nature} se termine {quand} ({fin}). Renouvelez-le depuis "
                f"Configuration : {montant} FCFA pour un mois.",
            )

        if abonnement.statut == 'actif' and aujourd_hui == abonnement.date_fin + timedelta(days=1):
            return (
                "Abonnement expiré",
                f"Votre abonnement a expiré le {fin}. Vous disposez de "
                f"{abonnement.delai_grace()} jours pour le renouveler avant que le "
                f"groupement passe en lecture seule.",
            )

        if aujourd_hui == abonnement.date_lecture_seule():
            return (
                "Groupement en lecture seule",
                "Votre groupement est maintenant en lecture seule : les données "
                "restent consultables, mais aucune nouvelle opération n'est possible "
                f"jusqu'au renouvellement ({montant} FCFA par mois).",
            )

        return None
