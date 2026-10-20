import hashlib
import json

from asgiref.sync import async_to_sync
from django.core.cache import cache
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status
from rest_framework.throttling import ScopedRateThrottle

from authentication.permissions import MESSAGE_GIE_DESACTIVE

from .calculs import calculer_indicateurs
from .ia_diagnostic import analyser_diagnostic
from .ia_chatbot import repondre_question

# Analyse IA réutilisée pendant 30 minutes tant que les chiffres ne changent pas
DUREE_CACHE_ANALYSE = 30 * 60


def _analyse_ia_en_cache(gie, indicateurs):
    """
    Appelle l'IA seulement si l'analyse de ces indicateurs n'est pas en cache.
    Une nouvelle opération change les indicateurs, donc la clé : l'analyse est
    alors refaite. Une réponse « indisponible » n'est jamais mise en cache.
    """
    empreinte = hashlib.sha256(
        json.dumps(indicateurs, sort_keys=True, default=str).encode()
    ).hexdigest()[:16]
    cle = f"diagnostic_ia_{gie.id}_{empreinte}"

    analyse = cache.get(cle)
    if analyse is None:
        analyse = async_to_sync(analyser_diagnostic)(indicateurs)
        if analyse.get('disponible'):
            cache.set(cle, analyse, DUREE_CACHE_ANALYSE)
    return analyse


class DiagnosticAPIView(APIView):
    """
    Retourne les indicateurs financiers et leur analyse par IA
    pour le groupement de l'utilisateur connecté.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        gie = getattr(request.user, 'gie', None)

        if gie is None:
            return Response(
                {
                    'detail': 'Aucun groupement associé à votre compte.'
                },
                status=status.HTTP_403_FORBIDDEN
            )

        # Groupement désactivé par l'administrateur de la plateforme
        if gie.statut == 'inactif':
            return Response(
                {'detail': MESSAGE_GIE_DESACTIVE},
                status=status.HTTP_403_FORBIDDEN
            )

        indicateurs = calculer_indicateurs(gie)

        analyse_ia = _analyse_ia_en_cache(gie, indicateurs)

        # Retourner les indicateurs même si l'IA est indisponible
        resultat = {
            'indicateurs': indicateurs,
            'intelligenceArtificielle': analyse_ia,
        }

        return Response(
            resultat,
            status=status.HTTP_200_OK
        )


class AssistantChatAPIView(APIView):
    """
    Répond aux questions financières en utilisant uniquement
    les indicateurs du groupement de l'utilisateur connecté.
    """

    permission_classes = [IsAuthenticated]
    # Chaque question est un appel payant au service IA
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'assistant'

    def post(self, request):
        gie = getattr(request.user, 'gie', None)

        if gie is None:
            return Response(
                {
                    'detail': 'Aucun groupement associé à votre compte.'
                },
                status=status.HTTP_403_FORBIDDEN
            )

        # Groupement désactivé par l'administrateur de la plateforme
        if gie.statut == 'inactif':
            return Response(
                {'detail': MESSAGE_GIE_DESACTIVE},
                status=status.HTTP_403_FORBIDDEN
            )

        question = request.data.get('question')

        if not isinstance(question, str):
            return Response(
                {
                    'detail': 'La question doit être une chaîne de caractères.'
                },
                status=status.HTTP_400_BAD_REQUEST
            )

        question = question.strip()

        if not question:
            return Response(
                {
                    'detail': 'Veuillez saisir une question.'
                },
                status=status.HTTP_400_BAD_REQUEST
            )

        if len(question) > 1000:
            return Response(
                {
                    'detail': (
                        'Votre question ne doit pas dépasser '
                        '1000 caractères.'
                    )
                },
                status=status.HTTP_400_BAD_REQUEST
            )

        indicateurs = calculer_indicateurs(gie)

        resultat = async_to_sync(repondre_question)(
            question,
            indicateurs
        )

        if not resultat.get('disponible'):
            return Response(
                {
                    'detail': resultat.get(
                        'message',
                        'Le service IA est momentanément indisponible.'
                    )
                },
                status=status.HTTP_503_SERVICE_UNAVAILABLE
            )

        return Response(
            {
                'reponse': resultat['reponse']
            },
            status=status.HTTP_200_OK
        )