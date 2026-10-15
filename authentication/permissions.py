from rest_framework.permissions import BasePermission


MESSAGE_GIE_DESACTIVE = (
    "Votre groupement a été désactivé. "
    "Contactez l'administrateur de SunuGestion."
)


def gie_utilisable(permission, utilisateur):
    """
    Vrai si l'utilisateur appartient à un GIE qui n'a pas été désactivé
    par l'administrateur. Sinon, adapte le message d'erreur renvoyé.
    """
    gie = getattr(utilisateur, 'gie', None)

    if gie is None:
        return False

    if gie.statut == 'inactif':
        permission.message = MESSAGE_GIE_DESACTIVE
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
            and gie_utilisable(self, request.user)
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
            and gie_utilisable(self, request.user)
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
            and gie_utilisable(self, request.user)
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
            and gie_utilisable(self, request.user)
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
            and gie_utilisable(self, request.user)
        )
