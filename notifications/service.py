from django.db import transaction

from .models import Notification, NotificationUtilisateur


def envoyer_notification(
    destinataires,
    titre: str,
    message: str,
    type_evenement: str,
    module: str,
    objet_id: int = None,
) -> Notification:
    """
    Crée une notification en base pour chaque destinataire. Elle est affichée
    dans la cloche de l'application (GET /api/notifications/).

    Paramètres :
    - destinataires  : queryset ou liste d'objets Utilisateur
    - titre          : titre de la notification (ex: "Nouvelle activité")
    - message        : corps de la notification
    - type_evenement : type d'événement (ex: "nouvelle_activite", "pret_approuve")
    - module         : module concerné pour le badge (ex: "activites", "prets")
    - objet_id       : ID de l'objet concerné — permet la navigation directe (optionnel)

    Retourne la notification créée.
    """

    # Convertir en liste pour pouvoir itérer plusieurs fois
    # (un queryset Django ne peut être parcouru qu'une seule fois de façon fiable)
    destinataires = list(destinataires)

    with transaction.atomic():

        # 1. Créer la notification en base
        notification = Notification.objects.create(
            titre=titre,
            message=message,
            type=type_evenement,
            module=module,
            objet_id=objet_id,
        )

        # 2. Créer les liaisons NotificationUtilisateur (lue=False par défaut)
        liaisons = [
            NotificationUtilisateur(
                notification=notification,
                utilisateur=destinataire,
            )
            for destinataire in destinataires
        ]
        NotificationUtilisateur.objects.bulk_create(liaisons)

    return notification
