from django.shortcuts import render


from drf_spectacular.plumbing import get_view_model
from drf_spectacular.utils import extend_schema
from rest_framework import status, viewsets
from rest_framework.decorators import APIView, action
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.response import Response

from authentication.models import Utilisateur

from .serializers import (
    AjoutMembreSerializer,
    ImportExcelSerializer,
    MembreSerializer,
)


# ==========================================================
# VÉRIFICATION DES DROITS
# ==========================================================

def verifier_permission(request_user):
    """
    Seul le Président ou le Secrétaire
    peut gérer l'ajout/import des membres.
    """

    return request_user.role in [
        'president',
        'secretaire'
    ]


# ==========================================================
# VIEWSET DES MEMBRES
# ==========================================================

class MembreViewSet(viewsets.ViewSet):

    permission_classes = [
        IsAuthenticated
    ]

    # ======================================================
    # 1. LISTER LES MEMBRES
    # GET /membres/
    # ======================================================

    def list(self, request):

        membres = Utilisateur.objects.filter(
            gie=request.user.gie
        ).order_by(
            'nom',
            'prenom'
        )

        serializer = MembreSerializer(
            membres,
            many=True
        )

        total = membres.count()
        actifs = membres.filter(statut='actif').count()
        inactifs = membres.filter(statut='inactif').count()
        en_attente = membres.filter(statut='en_attente').count()

        return Response(
            {
                'membres': serializer.data,
                'total': total,
                'actifs': actifs,
                'inactifs': inactifs,
                'en_attente': en_attente
            },
            status=status.HTTP_200_OK
        )

    # ======================================================
    # 2. DETAIL D'UN MEMBRE
    # GET /membres/<id>/
    # ======================================================

    def retrieve(self, request, pk=None):

        try:

            membre = Utilisateur.objects.get(
                id=pk,
                gie=request.user.gie
            )

        except Utilisateur.DoesNotExist:

            return Response(
                {
                    'erreur': 'Membre introuvable.'
                },
                status=status.HTTP_404_NOT_FOUND
            )

        serializer = MembreSerializer(
            membre
        )

        return Response(
            serializer.data,
            status=status.HTTP_200_OK
        )

    # ======================================================
    # 3. MODIFIER SES PROPRES INFORMATIONS
    # PATCH /membres/<id>/
    # ======================================================

    def partial_update(self, request, pk=None):

        # Vérifier que le membre existe
        try:

            membre = Utilisateur.objects.get(
                id=pk,
                gie=request.user.gie
            )

        except Utilisateur.DoesNotExist:

            return Response(
                {
                    'erreur': 'Membre introuvable.'
                },
                status=status.HTTP_404_NOT_FOUND
            )

        # Un membre ne peut modifier que son propre profil
        if membre.id != request.user.id:

            return Response(
                {
                    'erreur': (
                        'Vous ne pouvez modifier '
                        'que vos propres informations.'
                    )
                },
                status=status.HTTP_403_FORBIDDEN
            )

        serializer = MembreSerializer(
            membre,
            data=request.data,
            partial=True
        )

        if serializer.is_valid():

            membre = serializer.save()

            return Response(
                MembreSerializer(membre).data,
                status=status.HTTP_200_OK
            )

        return Response(
            serializer.errors,
            status=status.HTTP_400_BAD_REQUEST
        )

    # ======================================================
    # 4. AJOUTER MANUELLEMENT UN MEMBRE
    # POST /membres/ajouter/
    # ======================================================

    @extend_schema(
    request=AjoutMembreSerializer,
    responses={201: AjoutMembreSerializer}
)

    @action(
        detail=False,
        methods=['post'],
        url_path='ajouter'
    )
    def ajouter(self, request):

        if not verifier_permission(request.user):

            return Response(
                {
                    'erreur': (
                        'Accès refusé. '
                        'Seul le Président ou le Secrétaire '
                        'peut ajouter des membres.'
                    )
                },
                status=status.HTTP_403_FORBIDDEN
            )

        serializer = AjoutMembreSerializer(
            data=request.data,
            context={
                'gie': request.user.gie
            }
        )

        if serializer.is_valid():

            membre = serializer.save()

            return Response(
                {
                    'message': f'Membre ajouté avec succès.',
                    'token_invitation': membre.token_invitation, 
                    'membre': {
                        'id': membre.id,
                        'prenom': membre.prenom,
                        'nom': membre.nom,
                        'telephone': membre.telephone,
                        'role': membre.role,
                        'statut': membre.statut
                    }
                },
                status=status.HTTP_201_CREATED
            )

        return Response(
            serializer.errors,
            status=status.HTTP_400_BAD_REQUEST
        )

    # ======================================================
    # 5. ANALYSER LE FICHIER EXCEL
    # POST /membres/analyser-excel/
    # ======================================================

    @extend_schema(
        request=ImportExcelSerializer,
        responses={200: ImportExcelSerializer}
    )
    @action(
        detail=False,
        methods=['post'],
        url_path='analyser-excel'
    )
    def analyser_excel(self, request):

        if not verifier_permission(request.user):

            return Response(
                {
                    'erreur': 'Accès refusé.'
                },
                status=status.HTTP_403_FORBIDDEN
            )

        serializer = ImportExcelSerializer(
            data=request.FILES
        )

        if serializer.is_valid():

            membres_valides, membres_invalides = (
                serializer.analyser()
            )

            return Response(
                {
                    'membresValides': membres_valides,
                    'membresInvalides': membres_invalides,
                    'totalValides': len(membres_valides),
                    'totalInvalides': len(membres_invalides),
                },
                status=status.HTTP_200_OK
            )

        return Response(
            serializer.errors,
            status=status.HTTP_400_BAD_REQUEST
        )

    # ======================================================
    # 6. IMPORTER LES MEMBRES VALIDES
    # POST /membres/importer/
    # ======================================================

    @extend_schema(
    request=AjoutMembreSerializer,
    responses={201: AjoutMembreSerializer}
)

    @action(detail=False, methods=['post'], url_path='importer')
    def importer(self, request):
        if not verifier_permission(request.user):
            return Response(
                {'erreur': 'Accès refusé.'},
                status=status.HTTP_403_FORBIDDEN
            )

        membres_valides = request.data.get('membres', request.data.get('membresValides', []))

        if not membres_valides:
            return Response(
                {'erreur': "Le backend n'a reçu aucun membre à importer."},
                status=status.HTTP_400_BAD_REQUEST
            )

        utilisateurs_a_creer = []
        erreurs_de_validation = []

        # 1. Tri des membres reçu
        for index, item in enumerate(membres_valides):
            serializer = AjoutMembreSerializer(
                data=item, 
                context={'gie': request.user.gie}
            )
            
            if serializer.is_valid():
                user_instance = Utilisateur(
                    prenom=serializer.validated_data.get('prenom'),
                    nom=serializer.validated_data.get('nom'),
                    telephone=serializer.validated_data.get('telephone'),
                    role=serializer.validated_data.get('role'),
                    gie=request.user.gie
                )
                utilisateurs_a_creer.append(user_instance)
            else:
                erreurs_de_validation.append({
                    'ligne_excel': item.get('ligne', index + 2),
                    'membre': f"{item.get('prenom', '')} {item.get('nom', '')}",
                    'details_des_erreurs': serializer.errors
                })

        # 2. ON ENREGISTRE LES BONS ELEVES D'ABORD (Plus de blocage !)
        if utilisateurs_a_creer:
            try:
                Utilisateur.objects.bulk_create(utilisateurs_a_creer)
            except Exception as e:
                return Response(
                    {'erreur': f"Erreur technique lors de l'écriture en BDD : {str(e)}"},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR
                )

        # 3. ON CORRIGE LE RETOUR : On renvoie un statut 201 (Créé) avec le bilan complet
        return Response(
            {
                'message': f'{len(utilisateurs_a_creer)} membre(s) importé(s) avec succès.',
                'total_importes': len(utilisateurs_a_creer),
                'total_echoues': len(erreurs_de_validation),
                'erreurs': erreurs_de_validation  # Le frontend saura qui a échoué
            },
            status=status.HTTP_201_CREATED # <-- Fini l'erreur 400 automatique
        )


    @action(
    detail=False,
    methods=['post'],
    url_path='activation-compte',
    permission_classes=[AllowAny]  # 🔓 Accessible sans être connecté
    )

    def activation_publique(self, request):
        token = request.data.get('token')
        pin = request.data.get('pin')  # Le code PIN à 4 chiffres choisi par le membre

        if not token:
            return Response(
                {"erreur": "Le jeton d'activation est manquant."}, 
                status=status.HTTP_400_BAD_REQUEST
            )
            
        if not pin or not str(pin).isdigit() or len(str(pin)) != 4:
            return Response(
                {"erreur": "Le code PIN doit être un nombre de 4 chiffres."}, 
                status=status.HTTP_400_BAD_REQUEST
            )
            
        try:
            # Recherche de l'utilisateur avec son jeton d'invitation unique
            utilisateur = Utilisateur.objects.get(token_invitation=token)
            
            # Mise à jour du mot de passe (PIN) et passage au statut actif
            utilisateur.set_password(pin)
            utilisateur.statut = 'actif'
            utilisateur.is_active = True
            
            # 🔐 Sécurité : destruction du jeton d'invitation après son premier usage
            utilisateur.token_invitation = None
            utilisateur.save()
            
            return Response(
                {"message": "Votre compte a été activé avec succès !"}, 
                status=status.HTTP_200_OK
            )
            
        except Utilisateur.DoesNotExist:
            return Response(
                {"erreur": "Le lien d'activation est invalide ou a expiré."}, 
                status=status.HTTP_404_NOT_FOUND
            )


