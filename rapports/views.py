from django.http import HttpResponse
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from rest_framework.views import APIView

from authentication.permissions import EstPresidentOuTresorier
from rapports.serializers import RapportPeriodeSerializer
from rapports.services import (
    collecter_donnees_rapport,
    generer_rapport_pdf,
    obtenir_nom_fichier,
)


class RapportPeriodiqueView(APIView):
    """
    Génère le rapport périodique de gestion (PDF) du groupement
    de l'utilisateur connecté.
    """

    permission_classes = [EstPresidentOuTresorier]

    @extend_schema(
        parameters=[RapportPeriodeSerializer],
        responses={(200, 'application/pdf'): OpenApiTypes.BINARY},
    )
    def get(self, request):
        serializer = RapportPeriodeSerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)

        periode = serializer.validated_data

        # Le groupement est toujours celui de l'utilisateur connecté
        donnees = collecter_donnees_rapport(
            request.user.gie,
            periode['type_periode'],
            periode['annee'],
            periode['mois'],
            periode['trimestre']
        )

        pdf = generer_rapport_pdf(donnees)

        nom_fichier = obtenir_nom_fichier(
            periode['type_periode'],
            periode['annee'],
            periode['mois'],
            periode['trimestre']
        )

        reponse = HttpResponse(pdf, content_type='application/pdf')
        reponse['Content-Disposition'] = (
            f'attachment; filename="{nom_fichier}"'
        )

        return reponse
