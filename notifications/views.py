from rest_framework import generics, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import NotificationUtilisateur
from .serializers import NotificationListeSerializer

# Nombre maximal de notifications renvoyées par la liste
LIMITE_LISTE = 50


class NotificationListView(generics.GenericAPIView):
    """
    GET /api/notifications/
    Retourne les dernières notifications de l'utilisateur connecté
    (les plus récentes d'abord) et le nombre total de non lues.
    """

    serializer_class = NotificationListeSerializer
    permission_classes = [IsAuthenticated]

    def get(self, request):
        liaisons = NotificationUtilisateur.objects.filter(
            utilisateur=request.user
        )

        recentes = liaisons.select_related('notification').order_by(
            '-notification__date_creation', '-notification__id'
        )[:LIMITE_LISTE]

        return Response(
            {
                'notifications': self.get_serializer(recentes, many=True).data,
                'non_lues': liaisons.filter(lue=False).count(),
            },
            status=status.HTTP_200_OK
        )


class NotificationLireView(generics.GenericAPIView):
    """
    PATCH /api/notifications/<id>/lire/
    Marque une notification comme lue pour l'utilisateur connecté.
    """

    permission_classes = [IsAuthenticated]

    def patch(self, request, pk):
        modifiees = NotificationUtilisateur.objects.filter(
            utilisateur=request.user,
            notification_id=pk
        ).update(lue=True)

        # Notification inexistante ou destinée à un autre utilisateur
        if not modifiees:
            return Response(
                {'detail': 'Notification introuvable.'},
                status=status.HTTP_404_NOT_FOUND
            )

        return Response(
            {
                'id': pk,
                'lue': True,
                'non_lues': NotificationUtilisateur.objects.filter(
                    utilisateur=request.user, lue=False
                ).count(),
            },
            status=status.HTTP_200_OK
        )


class NotificationsToutLireView(generics.GenericAPIView):
    """
    PATCH /api/notifications/tout-lire/
    Marque toutes les notifications de l'utilisateur connecté comme lues.
    """

    permission_classes = [IsAuthenticated]

    def patch(self, request):
        nombre = NotificationUtilisateur.objects.filter(
            utilisateur=request.user,
            lue=False
        ).update(lue=True)

        return Response(
            {'nombre_marquees_lues': nombre, 'non_lues': 0},
            status=status.HTTP_200_OK
        )
