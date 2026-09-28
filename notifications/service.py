import logging

import firebase_admin
from firebase_admin import messaging
from django.db import transaction

from .models import FCMToken, Notification, NotificationUtilisateur

logger = logging.getLogger(__name__)


def envoyer_notification(
    destinataires,
    titre: str,
    message: str,
    type_evenement: str,
    module: str,
    objet_id: int = None,
) -> Notification:
    """
    Crée une notification en base et l'envoie via FCM à tous les appareils
    des destinataires.

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

    # 3. Envoyer la notification push via FCM (hors transaction)
    _envoyer_push(destinataires, titre, message, type_evenement, module, objet_id)

    return notification


def _envoyer_push(destinataires, titre, message, type_evenement, module, objet_id):
    """
    Envoie la notification push FCM à tous les tokens des destinataires.
    Les tokens invalides/désenregistrés sont supprimés automatiquement de la base.
    Les erreurs réseau ou temporaires sont loguées sans suppression.
    """

    # Firebase n'est pas forcément initialisé (credentials absents en dev)
    if not firebase_admin._apps:
        logger.warning(
            "FCM non initialisé — la notification push n'a pas été envoyée."
        )
        return

    # Erreurs FCM qui indiquent clairement un token définitivement invalide
    ERREURS_TOKEN_INVALIDE = {
        'NOT_FOUND',           # messaging.UnregisteredError
        'UNREGISTERED',        # variante selon la version firebase-admin
    }

    # Récupérer les objets FCMToken complets (besoin du token pour suppression)
    ids_destinataires = [u.id for u in destinataires]
    fcm_tokens = list(
        FCMToken.objects.filter(
            utilisateur_id__in=ids_destinataires
        )
    )

    if not fcm_tokens:
        logger.info("Aucun token FCM trouvé pour les destinataires — push ignoré.")
        return

    tokens = [fcm.token for fcm in fcm_tokens]

    # Construire le payload FCM
    # Les données (data) sont envoyées en plus de la notification visuelle
    # Angular les lit dans le service worker pour la navigation directe
    fcm_message = messaging.MulticastMessage(
        tokens=tokens,
        notification=messaging.Notification(
            title=titre,
            body=message,
        ),
        data={
            'type': type_evenement,
            'module': module,
            'objet_id': str(objet_id) if objet_id else '',
        },
    )

    try:
        response = messaging.send_each_for_multicast(fcm_message)
        logger.info(
            "FCM — %d envoyés, %d échoués.",
            response.success_count,
            response.failure_count,
        )

        if response.failure_count > 0:
            tokens_a_supprimer = []

            for idx, result in enumerate(response.responses):
                if result.success:
                    continue

                exc = result.exception
                logger.warning(
                    "FCM — échec pour le token index %d : %s",
                    idx,
                    exc,
                )

                # Supprimer uniquement les tokens définitivement invalides
                # (NotRegistered / UnregisteredError / NOT_FOUND)
                # On ne supprime pas les erreurs réseau ou temporaires
                if isinstance(exc, messaging.UnregisteredError):
                    tokens_a_supprimer.append(tokens[idx])
                else:
                    # Vérification par code d'erreur FCM pour les autres cas
                    code = getattr(exc, 'code', '') or ''
                    if any(invalide in code.upper() for invalide in ERREURS_TOKEN_INVALIDE):
                        tokens_a_supprimer.append(tokens[idx])

            if tokens_a_supprimer:
                suppression = FCMToken.objects.filter(token__in=tokens_a_supprimer).delete()
                logger.info(
                    "FCM — %d token(s) invalide(s) supprimé(s) de la base.",
                    suppression[0],
                )

    except Exception as exc:
        logger.error("FCM — erreur inattendue lors de l'envoi : %s", exc)


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
