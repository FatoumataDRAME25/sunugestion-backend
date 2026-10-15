from asgiref.sync import async_to_sync
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status

from authentication.permissions import MESSAGE_GIE_DESACTIVE

from .calculs import calculer_indicateurs
from .ia_diagnostic import analyser_diagnostic
from .ia_chatbot import repondre_question


class DiagnosticAPIView(APIView):
    """
    Retourne les indicateurs financiers et leur analyse par IA
    pour le groupement de l'utilisateur connecté.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        # 1. Récupérer le groupement de l'utilisateur connecté
        gie = getattr(request.user, 'gie', None)

        # 2. Refuser l'accès si aucun groupement n'est associé
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

        # 3. Calculer les indicateurs financiers
        indicateurs = calculer_indicateurs(gie)

        # 4. Appeler l'analyse IA asynchrone depuis la vue synchrone
        analyse_ia = async_to_sync(analyser_diagnostic)(indicateurs)

        # 5. Retourner les indicateurs même si l'IA est indisponible
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

    def post(self, request):
        # 1. Vérifier que l'utilisateur appartient à un groupement
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

        # 2. Récupérer et valider la question
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

        # 3. Calculer les indicateurs du groupement connecté
        indicateurs = calculer_indicateurs(gie)

        # 4. Interroger l'assistant IA
        resultat = async_to_sync(repondre_question)(
            question,
            indicateurs
        )

        # 5. Gérer l'indisponibilité du service IA
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

        # 6. Retourner la réponse au frontend
        return Response(
            {
                'reponse': resultat['reponse']
            },
            status=status.HTTP_200_OK
        )