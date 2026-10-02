from rest_framework.permissions import BasePermission


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
            and request.user.gie is not None
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
            and request.user.gie is not None
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
            and request.user.gie is not None
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
            and request.user.gie is not None
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
            and request.user.gie is not None
        )
