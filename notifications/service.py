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


def marquer_module_comme_lu(utilisateur, module: str) -> int:
    """
    Marque toutes les notifications non lues d'un module comme lues
    pour un utilisateur donné.

    Appelé quand l'utilisateur ouvre un module (ex: ouvre "Activités").
    Retourne le nombre de notifications marquées comme lues.
    """
    nombre = NotificationUtilisateur.objects.filter(
        utilisateur=utilisateur,
        lue=False,
        notification__module=module,
    ).update(lue=True)

    return nombre


def compter_non_lues_par_module(utilisateur) -> dict:
    """
    Retourne le nombre de notifications non lues par module pour un utilisateur,
    ainsi que le dernier objet_id non lu (pour navigation directe si count == 1).

    Exemple de retour :
    {
        "activites":   { "count": 1, "dernier_objet_id": 15 },
        "cotisations": { "count": 2, "dernier_objet_id": null },
        "prets":       { "count": 0, "dernier_objet_id": null },
        "membres":     { "count": 0, "dernier_objet_id": null },
        "general":     { "count": 0, "dernier_objet_id": null },
    }
    Utilisé par Angular pour afficher les badges et naviguer intelligemment.
    """
    modules = [choix[0] for choix in Notification.MODULE_CHOICES]

    badges = {}
    for module in modules:
        qs = NotificationUtilisateur.objects.filter(
            utilisateur=utilisateur,
            lue=False,
            notification__module=module,
        ).select_related('notification')

        count = qs.count()

        # Si exactement 1 notification non lue, on retourne son objet_id
        # pour permettre la navigation directe vers le détail
        dernier_objet_id = None
        if count == 1:
            dernier_objet_id = qs.first().notification.objet_id

        badges[module] = {
            'count': count,
            'dernierObjetId': dernier_objet_id,
        }

    return badges
