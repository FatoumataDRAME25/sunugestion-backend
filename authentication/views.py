from django.utils import timezone

from dateutil.relativedelta import relativedelta
from django.db.models.aggregates import Count
from django.shortcuts import render
from drf_spectacular.utils import extend_schema

from rest_framework.views import APIView
from rest_framework.generics import RetrieveUpdateAPIView
from rest_framework import status
from rest_framework.response import Response
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework_simplejwt.tokens import RefreshToken
from django.contrib.auth import get_user_model
from rest_framework.generics import ListAPIView

from authentication.models import GIE

from .serializers import (
    ConnexionSerializer,
    DeconnexionSerializer,
    GIECreationSerializer,
    GIESerializer,
    InscriptionPresidentSerializer,
    VerifierOTPSerializer
)

Utilisateur = get_user_model()


def get_tokens(user):
    """Génère les tokens JWT pour un utilisateur"""
    refresh = RefreshToken.for_user(user)
    return {
        'refresh': str(refresh),
        'access': str(refresh.access_token),
    }


class CreerGIEView(APIView):
    """
    Étape 1 — Le Président crée son GIE.
    Retourne un token d'inscription temporaire.
    """
    permission_classes = [AllowAny]

    serializer_class = GIECreationSerializer
    @extend_schema(
    request=GIECreationSerializer
   )

    def post(self, request):
        serializer = self.serializer_class(data=request.data)

        if serializer.is_valid():
            gie = serializer.save()
            return Response({
                'message': 'GIE créé avec succès.',
                'tokenInscription': gie.token_inscription,
                'code': gie.code
            }, status=status.HTTP_201_CREATED)

        return Response(
            serializer.errors,
            status=status.HTTP_400_BAD_REQUEST
        )

# lister les GIE
class ListeGIEView(ListAPIView):
    queryset = GIE.objects.all().order_by('-date_creation')
    serializer_class = GIESerializer
    permission_classes = [AllowAny]


# Voir detail d'un GIE
class DetailGIEView(RetrieveUpdateAPIView):
    queryset = GIE.objects.all()
    serializer_class = GIESerializer
    permission_classes = [AllowAny]


class StatistiquesGIEView(APIView):

    permission_classes = [AllowAny]
    serializer_class = GIESerializer

    @extend_schema(
        request=GIESerializer
    )

    def get(self, request):
        
        total_gies = GIE.objects.count()

        gies_actifs = GIE.objects.filter(
            statut='actif'
        ).count()

        gies_inactifs = GIE.objects.filter(
            statut='inactif'
        ).count()


        total_regions = GIE.objects.values(
            'region'
        ).distinct().count()

        total_secteurs = GIE.objects.values(
            'secteur'
        ).distinct().count()

        total_membres = Utilisateur.objects.filter(
            gie__isnull=False
        ).count()

        return Response({
            'total_gies': total_gies,
            'gies_actifs': gies_actifs,
            'gies_inactifs': gies_inactifs,
            'total_regions': total_regions,
            'total_secteurs': total_secteurs,
            'total_membres': total_membres,
        })

class InscriptionPresidentView(APIView):
    """
    Étape 2 — Le Président renseigne ses informations + PIN.
    Le système génère et envoie un OTP par SMS.
    """
    permission_classes = [AllowAny]

    @extend_schema(
        request=InscriptionPresidentSerializer
    )

    def post(self, request):
        serializer = InscriptionPresidentSerializer(data=request.data)

        if serializer.is_valid():
            president = serializer.save()
            return Response({
                'message': f'Code OTP envoyé au {president.telephone}.',
            }, status=status.HTTP_201_CREATED)

        return Response(
            serializer.errors,
            status=status.HTTP_400_BAD_REQUEST
        )


class VerifierOTPView(APIView):
    """
    Étape 3 — Le Président saisit son code OTP.
    Le système active le compte et retourne les tokens JWT.
    """
    permission_classes = [AllowAny]

    @extend_schema(
        request=VerifierOTPSerializer
    )

    def post(self, request):
        serializer = VerifierOTPSerializer(data=request.data)

        if serializer.is_valid():
            president = serializer.activer_compte()
            tokens = get_tokens(president)
            return Response({
                'message': 'Compte activé avec succès.',
                'tokens': tokens,
                'utilisateur': {
                    'id': president.id,
                    'nom': president.nom,
                    'prenom': president.prenom,
                    'telephone': president.telephone,
                    'role': president.role,
                    'gie': president.gie.nom
                }
            }, status=status.HTTP_200_OK)

        return Response(
            serializer.errors,
            status=status.HTTP_400_BAD_REQUEST
        )



class ConnexionView(APIView):
    """
    Connexion par numéro de téléphone + PIN.
    Retourne les tokens JWT si les identifiants sont corrects.
    """
    permission_classes = [AllowAny]

    @extend_schema(
        request=ConnexionSerializer
    )

    def post(self, request):
        serializer = ConnexionSerializer(data=request.data)

        if serializer.is_valid():
            utilisateur = serializer.validated_data['utilisateur']
            tokens = get_tokens(utilisateur)
            return Response({
                'message': 'Connexion réussie.',
                'tokens': tokens,
                'utilisateur': {
                    'id': utilisateur.id,
                    'nom': utilisateur.nom,
                    'prenom': utilisateur.prenom,
                    'telephone': utilisateur.telephone,
                    'role': utilisateur.role,
                    'gie': utilisateur.gie.nom if utilisateur.gie else None
                }
            }, status=status.HTTP_200_OK)

        return Response(
            serializer.errors,
            status=status.HTTP_400_BAD_REQUEST
        )



class DeconnexionView(APIView):
    """
    Déconnexion — blackliste le refresh token.
    Le token access reste valide jusqu'à son expiration.
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(
        request=DeconnexionSerializer
    )
    def post(self, request):
        serializer = DeconnexionSerializer(data=request.data)

        if serializer.is_valid():
            return Response({
                'message': 'Déconnexion réussie.'
            }, status=status.HTTP_200_OK)

        return Response(
            serializer.errors,
            status=status.HTTP_400_BAD_REQUEST
        )


class EvolutionGIEView(APIView):
    permission_classes = [AllowAny]


    def get(self, request):

        mois_francais = {
            'January': 'Janvier',
            'February': 'Février',
            'March': 'Mars',
            'April': 'Avril',
            'May': 'Mai',
            'June': 'Juin',
            'July': 'Juillet',
            'August': 'Août',
            'September': 'Septembre',
            'October': 'Octobre',
            'November': 'Novembre',
            'December': 'Décembre',
        }
        aujourd_hui = timezone.now()

        resultats = []

        for i in range(4, -1, -1):
            date_mois = aujourd_hui - relativedelta(months=i)

            debut_mois = date_mois.replace(
                day=1,
                hour=0,
                minute=0,
                second=0,
                microsecond=0
            )

            fin_mois = debut_mois + relativedelta(months=1)

            total = GIE.objects.filter(
                date_creation__lt=fin_mois
            ).count()

            resultats.append({
                'mois': mois_francais[debut_mois.strftime('%B')],
                'total': total
            })

        return Response(resultats)


class RepartitionSecteursView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):

        # Nombre total de GIE
        total_gies = GIE.objects.count()

        # Nombre de GIE par secteur
        gies_par_secteur = GIE.objects.values(
            'secteur'
        ).annotate(
            total=Count('id')
        )

        resultats = []

        # Éviter une division par zéro
        if total_gies == 0:
            return Response(resultats)

        # Calcul du pourcentage pour chaque secteur
        for item in gies_par_secteur:

            pourcentage = (item['total'] / total_gies) * 100

            resultats.append({
                'secteur': item['secteur'],
                'pourcentage': round(pourcentage, 2)
            })

        return Response(resultats)