from rest_framework.permissions import SAFE_METHODS, BasePermission


MESSAGE_GIE_DESACTIVE = (
    "Votre groupement a été désactivé. "
    "Contactez l'administrateur de SunuGestion."
)

MESSAGE_LECTURE_SEULE = (
    "L'abonnement de votre groupement a expiré : le groupement est en lecture "
    "seule jusqu'au renouvellement. Le président ou le trésorier peut le "
    "renouveler depuis la page Configuration."
)


def _autorise_en_lecture_seule(view):
    """
    Opérations permises même quand l'abonnement a expiré : payer
    l'abonnement, modifier son propre profil ou son code PIN.
    Une vue l'indique avec `autorise_en_lecture_seule = True`, un ViewSet
    avec `actions_autorisees_en_lecture_seule = {...}`.
    """
    if getattr(view, 'autorise_en_lecture_seule', False):
        return True
    return getattr(view, 'action', None) in getattr(
        view, 'actions_autorisees_en_lecture_seule', ()
    )


def gie_utilisable(permission, request, view=None):
    """
    Vrai si l'utilisateur appartient à un GIE utilisable pour cette requête :
    - le GIE n'a pas été désactivé par l'administrateur ;
    - pour une modification (POST, PATCH…), l'abonnement n'est pas en
      lecture seule.
    Sinon, adapte le message d'erreur renvoyé.
    """
    gie = getattr(request.user, 'gie', None)

    if gie is None:
        return False

    if gie.statut == 'inactif':
        permission.message = MESSAGE_GIE_DESACTIVE
        return False

    if request.method not in SAFE_METHODS and not _autorise_en_lecture_seule(view):
        # Import local : l'application abonnements dépend de authentication
        from abonnements.services import acces_ecriture_autorise

        if not acces_ecriture_autorise(gie):
            permission.message = MESSAGE_LECTURE_SEULE
            return False

    return True


class EstMembreGIE(BasePermission):
    """
    Autorise uniquement les utilisateurs appartenant à un GIE.
    Bloque explicitement l'administrateur plateforme.
    """
    message = "Accès réservé aux membres d'un GIE."

    def has_permission(self, request, view):
        return (
            request.user
            and request.user.is_authenticated
            and request.user.role != 'administrateur'
            and gie_utilisable(self, request, view)
        )


class EstAdministrateur(BasePermission):
    """
    Autorise uniquement l'administrateur plateforme.
    """
    message = "Accès réservé à l'administrateur."

    def has_permission(self, request, view):
        return (
            request.user
            and request.user.is_authenticated
            and request.user.role == 'administrateur'
        )


class EstPresident(BasePermission):
    """
    Autorise uniquement le président d'un GIE.
    """
    message = "Accès réservé au président."

    def has_permission(self, request, view):
        return (
            request.user
            and request.user.is_authenticated
            and request.user.role == 'president'
            and gie_utilisable(self, request, view)
        )


class EstPresidentOuSecretaire(BasePermission):
    """
    Autorise le président ou le secrétaire d'un GIE.
    """
    message = "Accès réservé au président ou au secrétaire."

    def has_permission(self, request, view):
        return (
            request.user
            and request.user.is_authenticated
            and request.user.role in ('president', 'secretaire')
            and gie_utilisable(self, request, view)
        )


class EstPresidentOuTresorier(BasePermission):
    """
    Autorise le président ou le trésorier d'un GIE.
    """
    message = "Accès réservé au président ou au trésorier."

    def has_permission(self, request, view):
        return (
            request.user
            and request.user.is_authenticated
            and request.user.role in ('president', 'tresorier')
            and gie_utilisable(self, request, view)
        )


class EstTresorier(BasePermission):
    """
    Autorise uniquement le trésorier d'un GIE.
    """
    message = "Accès réservé au trésorier."

    def has_permission(self, request, view):
        return (
            request.user
            and request.user.is_authenticated
            and request.user.role == 'tresorier'
            and gie_utilisable(self, request, view)
        )
