from rest_framework import generics, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import Notification
from .serializers import FCMTokenSerializer
from .service import compter_non_lues_par_module, marquer_module_comme_lu

# Modules valides extraits des choices du modèle
MODULES_VALIDES = [choix[0] for choix in Notification.MODULE_CHOICES]


class FCMTokenCreateView(generics.GenericAPIView):

    serializer_class = FCMTokenSerializer
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        fcm_token = serializer.save()

        return Response(
            FCMTokenSerializer(fcm_token).data,
            status=status.HTTP_201_CREATED
        )


class BadgesView(generics.GenericAPIView):
    """
    GET /api/notifications/badges/
    Retourne le nombre de notifications non lues par module
    pour l'utilisateur connecté.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        badges = compter_non_lues_par_module(request.user)
        return Response(badges, status=status.HTTP_200_OK)


class MarquerModuleLuView(generics.GenericAPIView):
    """
    PATCH /api/notifications/badges/<module>/lire/
    Marque toutes les notifications non lues d'un module comme lues
    pour l'utilisateur connecté.
    """

    permission_classes = [IsAuthenticated]

    def patch(self, request, module):

        # Vérifier que le module fourni est valide
        if module not in MODULES_VALIDES:
            return Response(
                {
                    'detail': (
                        f"Module invalide : '{module}'. "
                        f"Valeurs autorisées : {', '.join(MODULES_VALIDES)}."
                    )
                },
                status=status.HTTP_400_BAD_REQUEST
            )

        nombre = marquer_module_comme_lu(request.user, module)

        return Response(
            {
                'module': module,
                'nombre_marquees_lues': nombre,
            },
            status=status.HTTP_200_OK
        )
