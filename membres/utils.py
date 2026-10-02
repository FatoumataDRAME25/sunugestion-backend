"""
Utilitaires partagés pour le module membres.

Centralise la logique d'envoi d'invitation afin que tous les flux
(ajout manuel, import Excel, import photo/OCR) utilisent exactement
le même mécanisme.

Quand Africa's Talking sera intégré, seul ce fichier devra être modifié.
"""


def envoyer_invitation(utilisateur) -> None:
    """
    Envoie le lien d'activation au membre via SMS.

    Le membre doit déjà avoir un `token_invitation` généré et sauvegardé
    en base avant d'appeler cette fonction.

    Paramètres :
    - utilisateur : instance Utilisateur avec token_invitation renseigné
    """
    lien = f"http://localhost:4200/activation?token={utilisateur.token_invitation}"

    # ── Simulation SMS (à remplacer par Africa's Talking) ──────────────────
    print("\n" + "=" * 60)
    print(f"📱 [SIMULATION SMS] Envoyé au {utilisateur.telephone}")
    print(f"Message : Bienvenue sur SunuGestion ! Activez votre compte ici : {lien}")
    print("=" * 60 + "\n")

    # TODO : remplacer le bloc ci-dessus par l'appel Africa's Talking :
    # from africastalking import SMS
    # SMS.send(message=f"Activez votre compte : {lien}", recipients=[f"+221{utilisateur.telephone}"])
