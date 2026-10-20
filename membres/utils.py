"""
Utilitaires partagés pour le module membres.

Centralise la logique d'envoi d'invitation afin que tous les flux
(ajout manuel, import Excel, import photo/OCR) utilisent exactement
le même mécanisme.

Quand Africa's Talking sera intégré, seul ce fichier devra être modifié.
"""

import logging

logger = logging.getLogger(__name__)


def envoyer_invitation(utilisateur) -> None:
    """
    Envoie le lien d'activation au membre via SMS.

    Le membre doit déjà avoir un `token_invitation` généré et sauvegardé
    en base avant d'appeler cette fonction.

    Paramètres :
    - utilisateur : instance Utilisateur avec token_invitation renseigné
    """
    # Le lien d'activation donne accès au compte : il n'est jamais écrit dans
    # les journaux. Le président l'envoie par WhatsApp depuis l'application.
    logger.info(
        "Invitation prête pour le membre %s (envoi par SMS non configuré).",
        utilisateur.id,
    )

    # TODO : envoi par SMS via Africa's Talking, par exemple :
    # lien = f"{settings.APP_URL}/activation?token={utilisateur.token_invitation}"
    # SMS.send(message=f"Activez votre compte : {lien}", recipients=[f"+221{utilisateur.telephone}"])
