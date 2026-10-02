from django.db import transaction
from drf_spectacular.utils import extend_schema
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from authentication.models import Utilisateur
from authentication.permissions import (
    EstMembreGIE,
    EstPresident,
    EstPresidentOuSecretaire,
)
from notifications.service import envoyer_notification

from .serializers import (
    AjoutMembreSerializer,
    ImportExcelSerializer,
    MembreSerializer,
)

ROLES_AUTORISES = ['president', 'tresorier', 'secretaire', 'membre']


class MembreViewSet(viewsets.ViewSet):
    """
    ViewSet du module Membres.

    Permissions par action :
    - list / retrieve            → EstMembreGIE (tout rôle GIE, admin exclu)
    - ajouter / analyser / importer → EstPresidentOuSecretaire
    - partial_update / changer_pin  → EstMembreGIE (propre profil uniquement)
    - modifier_role              → EstPresident
    - suspendre / reactiver      → EstPresident
    - activation_publique        → AllowAny
    """

    def get_permissions(self):
        if self.action == 'activation_publique':
            return [AllowAny()]
        if self.action in ('ajouter', 'analyser_excel', 'importer'):
            return [EstPresidentOuSecretaire()]
        if self.action in ('modifier_role', 'suspendre', 'reactiver'):
            return [EstPresident()]
        if self.action in ('partial_update', 'changer_pin'):
            return [EstMembreGIE()]
        # list, retrieve et tout le reste
        return [EstMembreGIE()]

    # ──────────────────────────────────────────────────────
    # Helper interne : récupère un membre du même GIE ou 404
    # ──────────────────────────────────────────────────────

    def _get_membre_du_gie(self, pk, gie):
        """
        Retourne le membre dont l'id=pk appartient au gie donné.
        Retourne None si introuvable (appelant doit renvoyer 404).
        """
        try:
            return Utilisateur.objects.get(id=pk, gie=gie)
        except Utilisateur.DoesNotExist:
            return None

    # ──────────────────────────────────────────────────────
    # 1. LISTER LES MEMBRES
    # GET /api/membres/
    # ──────────────────────────────────────────────────────

    def list(self, request):
        membres = Utilisateur.objects.filter(
            gie=request.user.gie
        ).order_by('nom', 'prenom')

        serializer = MembreSerializer(membres, many=True)

        return Response(
            {
                'membres': serializer.data,
                'total': membres.count(),
                'actifs': membres.filter(statut='actif').count(),
                'inactifs': membres.filter(statut='inactif').count(),
                'en_attente': membres.filter(statut='en_attente').count(),
            },
            status=status.HTTP_200_OK
        )

    # ──────────────────────────────────────────────────────
    # 2. DÉTAIL D'UN MEMBRE
    # GET /api/membres/<id>/
    # ──────────────────────────────────────────────────────

    def retrieve(self, request, pk=None):
        membre = self._get_membre_du_gie(pk, request.user.gie)
        if not membre:
            return Response(
                {'erreur': 'Membre introuvable.'},
                status=status.HTTP_404_NOT_FOUND
            )
        return Response(MembreSerializer(membre).data, status=status.HTTP_200_OK)

    # ──────────────────────────────────────────────────────
    # 3. MODIFIER SON PROPRE PROFIL
    # PATCH /api/membres/<id>/
    # Champs autorisés : prenom, nom, telephone, email
    # Champs protégés  : role, statut, gie (read_only dans le serializer)
    # ──────────────────────────────────────────────────────

    def partial_update(self, request, pk=None):
        membre = self._get_membre_du_gie(pk, request.user.gie)
        if not membre:
            return Response(
                {'erreur': 'Membre introuvable.'},
                status=status.HTTP_404_NOT_FOUND
            )

        # Chaque utilisateur ne peut modifier que son propre profil
        if membre.id != request.user.id:
            return Response(
                {'erreur': 'Vous ne pouvez modifier que vos propres informations.'},
                status=status.HTTP_403_FORBIDDEN
            )

        serializer = MembreSerializer(membre, data=request.data, partial=True)
        if serializer.is_valid():
            membre = serializer.save()
            return Response(MembreSerializer(membre).data, status=status.HTTP_200_OK)

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    # ──────────────────────────────────────────────────────
    # 4. AJOUTER MANUELLEMENT UN MEMBRE
    # POST /api/membres/ajouter/
    # Accès : président, secrétaire
    # ──────────────────────────────────────────────────────

    @extend_schema(request=AjoutMembreSerializer, responses={201: AjoutMembreSerializer})
    @action(detail=False, methods=['post'], url_path='ajouter')
    def ajouter(self, request):
        serializer = AjoutMembreSerializer(
            data=request.data,
            context={'gie': request.user.gie}
        )

        if serializer.is_valid():
            membre = serializer.save()

            envoyer_notification(
                destinataires=Utilisateur.objects.filter(
                    gie=request.user.gie,
                    role__in=['president', 'secretaire'],
                    statut='actif',
                ).exclude(id=request.user.id),
                titre='Nouveau membre ajouté',
                message=f'{membre.prenom} {membre.nom} a été ajouté au GIE.',
                type_evenement='nouveau_membre',
                module='membres',
                objet_id=membre.id,
            )

            return Response(
                {
                    'message': 'Membre ajouté avec succès.',
                    'tokenInvitation': membre.token_invitation,
                    'membre': {
                        'id': membre.id,
                        'prenom': membre.prenom,
                        'nom': membre.nom,
                        'telephone': membre.telephone,
                        'role': membre.role,
                        'statut': membre.statut,
                    },
                },
                status=status.HTTP_201_CREATED
            )

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    # ──────────────────────────────────────────────────────
    # 5. ANALYSER UN FICHIER EXCEL
    # POST /api/membres/analyser-excel/
    # Accès : président, secrétaire
    # ──────────────────────────────────────────────────────

    @extend_schema(request=ImportExcelSerializer, responses={200: ImportExcelSerializer})
    @action(detail=False, methods=['post'], url_path='analyser-excel')
    def analyser_excel(self, request):
        serializer = ImportExcelSerializer(data=request.FILES)

        if serializer.is_valid():
            membres_valides, membres_invalides = serializer.analyser()
            return Response(
                {
                    'membresValides': membres_valides,
                    'membresInvalides': membres_invalides,
                    'totalValides': len(membres_valides),
                    'totalInvalides': len(membres_invalides),
                },
                status=status.HTTP_200_OK
            )

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    # ──────────────────────────────────────────────────────
    # 6. IMPORTER LES MEMBRES VALIDES
    # POST /api/membres/importer/
    # Accès : président, secrétaire
    # ──────────────────────────────────────────────────────

    @extend_schema(request=AjoutMembreSerializer, responses={201: AjoutMembreSerializer})
    @action(detail=False, methods=['post'], url_path='importer')
    def importer(self, request):
        import secrets
        from django.db import transaction

        membres_valides = request.data.get('membres', request.data.get('membresValides', []))

        if not membres_valides:
            return Response(
                {'erreur': "Aucun membre à importer."},
                status=status.HTTP_400_BAD_REQUEST
            )

        utilisateurs_a_creer = []
        erreurs_de_validation = []
        # Suivre les téléphones déjà vus dans ce batch pour éviter
        # un crash PostgreSQL si deux lignes ont le même numéro
        telephones_du_batch = set()

        for index, item in enumerate(membres_valides):
            serializer = AjoutMembreSerializer(
                data=item,
                context={'gie': request.user.gie}
            )
            if serializer.is_valid():
                telephone = serializer.validated_data.get('telephone')

                # Doublon interne au batch
                if telephone in telephones_du_batch:
                    erreurs_de_validation.append({
                        'ligne_excel': item.get('ligne', index + 2),
                        'membre': f"{item.get('prenom', '')} {item.get('nom', '')}",
                        'details_des_erreurs': {
                            'telephone': ["Ce numéro apparaît plusieurs fois dans le fichier."]
                        },
                    })
                    continue

                telephones_du_batch.add(telephone)

                # Générer le token d'invitation sans appeler save()
                # (même mécanique que generer_token_invitation() mais sans persister)
                token = secrets.token_urlsafe(32)

                utilisateurs_a_creer.append(Utilisateur(
                    prenom=serializer.validated_data.get('prenom'),
                    nom=serializer.validated_data.get('nom'),
                    telephone=telephone,
                    role=serializer.validated_data.get('role'),
                    gie=request.user.gie,
                    statut='en_attente',
                    token_invitation=token,
                    # Pas de mot de passe — le membre le choisit lors de l'activation
                ))
            else:
                erreurs_de_validation.append({
                    'ligne_excel': item.get('ligne', index + 2),
                    'membre': f"{item.get('prenom', '')} {item.get('nom', '')}",
                    'details_des_erreurs': serializer.errors,
                })

        if utilisateurs_a_creer:
            try:
                with transaction.atomic():
                    Utilisateur.objects.bulk_create(utilisateurs_a_creer)
            except Exception as exc:
                return Response(
                    {'erreur': f"Erreur lors de l'import : {str(exc)}"},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR
                )

            # Après bulk_create(), envoyer les invitations SMS
            # via le même mécanisme que l'ajout manuel
            from membres.utils import envoyer_invitation
            for utilisateur in utilisateurs_a_creer:
                envoyer_invitation(utilisateur)
                # TODO : intégrer l'envoi réel avec Africa's Talking ici

        membres_importes_data = [
            {
                'prenom': u.prenom,
                'nom': u.nom,
                'telephone': u.telephone,
                'tokenInvitation': u.token_invitation,
            }
            for u in utilisateurs_a_creer
        ]

        return Response(
            {
                'message': f'{len(utilisateurs_a_creer)} membre(s) importé(s) avec succès.',
                'totalImportes': len(utilisateurs_a_creer),
                'totalEchoues': len(erreurs_de_validation),
                'membresImportes': membres_importes_data,
                'erreurs': erreurs_de_validation,
            },
            status=status.HTTP_201_CREATED
        )

    # ──────────────────────────────────────────────────────
    # 7. MODIFIER LE RÔLE D'UN MEMBRE
    # PATCH /api/membres/<id>/modifier-role/
    # Accès : président uniquement
    # Le président peut modifier son propre rôle (renouvellement de bureau)
    # ──────────────────────────────────────────────────────

    @action(detail=True, methods=['patch'], url_path='modifier-role')
    def modifier_role(self, request, pk=None):
        membre = self._get_membre_du_gie(pk, request.user.gie)
        if not membre:
            return Response(
                {'erreur': 'Membre introuvable.'},
                status=status.HTTP_404_NOT_FOUND
            )

        nouveau_role = request.data.get('role', '').strip().lower()
        if nouveau_role not in ROLES_AUTORISES:
            return Response(
                {
                    'erreur': (
                        f"Rôle invalide. Valeurs autorisées : "
                        f"{', '.join(ROLES_AUTORISES)}."
                    )
                },
                status=status.HTTP_400_BAD_REQUEST
            )

        with transaction.atomic():
            membre.role = nouveau_role
            membre.save(update_fields=['role'])

        return Response(
            {
                'message': f"Rôle mis à jour : {membre.prenom} {membre.nom} → {nouveau_role}.",
                'membre': MembreSerializer(membre).data,
            },
            status=status.HTTP_200_OK
        )

    # ──────────────────────────────────────────────────────
    # 8. SUSPENDRE UN MEMBRE
    # PATCH /api/membres/<id>/suspendre/
    # Accès : président uniquement
    # Le président ne peut pas se suspendre lui-même
    # ──────────────────────────────────────────────────────

    @action(detail=True, methods=['patch'], url_path='suspendre')
    def suspendre(self, request, pk=None):
        membre = self._get_membre_du_gie(pk, request.user.gie)
        if not membre:
            return Response(
                {'erreur': 'Membre introuvable.'},
                status=status.HTTP_404_NOT_FOUND
            )

        if membre.id == request.user.id:
            return Response(
                {'erreur': 'Vous ne pouvez pas vous suspendre vous-même.'},
                status=status.HTTP_403_FORBIDDEN
            )

        if membre.statut == 'inactif':
            return Response(
                {'erreur': 'Ce membre est déjà suspendu.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        membre.statut = 'inactif'
        membre.save(update_fields=['statut'])

        return Response(
            {
                'message': f"{membre.prenom} {membre.nom} a été suspendu.",
                'membre': MembreSerializer(membre).data,
            },
            status=status.HTTP_200_OK
        )

    # ──────────────────────────────────────────────────────
    # 9. RÉACTIVER UN MEMBRE
    # PATCH /api/membres/<id>/reactiver/
    # Accès : président uniquement
    # ──────────────────────────────────────────────────────

    @action(detail=True, methods=['patch'], url_path='reactiver')
    def reactiver(self, request, pk=None):
        membre = self._get_membre_du_gie(pk, request.user.gie)
        if not membre:
            return Response(
                {'erreur': 'Membre introuvable.'},
                status=status.HTTP_404_NOT_FOUND
            )

        if membre.statut == 'actif':
            return Response(
                {'erreur': 'Ce membre est déjà actif.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        membre.statut = 'actif'
        membre.save(update_fields=['statut'])

        return Response(
            {
                'message': f"{membre.prenom} {membre.nom} a été réactivé.",
                'membre': MembreSerializer(membre).data,
            },
            status=status.HTTP_200_OK
        )

    # ──────────────────────────────────────────────────────
    # 11. CHANGER SON CODE PIN
    # POST /api/membres/changer-pin/
    # Accès : tout membre GIE (EstMembreGIE)
    # ──────────────────────────────────────────────────────

    @action(detail=False, methods=['post'], url_path='changer-pin')
    def changer_pin(self, request):
        pin_actuel = request.data.get('pinActuel', '')
        nouveau_pin = request.data.get('nouveauPin', '')
        confirmation_pin = request.data.get('confirmationPin', '')

        # Vérification des champs obligatoires
        if not pin_actuel or not nouveau_pin or not confirmation_pin:
            return Response(
                {'erreur': "Tous les champs sont obligatoires."},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Format PIN : exactement 4 chiffres
        if not str(nouveau_pin).isdigit() or len(str(nouveau_pin)) != 4:
            return Response(
                {'erreur': "Le nouveau code PIN doit être un nombre de 4 chiffres."},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Confirmation
        if str(nouveau_pin) != str(confirmation_pin):
            return Response(
                {'erreur': "Le nouveau PIN et la confirmation ne correspondent pas."},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Vérification du PIN actuel
        utilisateur = request.user
        if not utilisateur.check_password(str(pin_actuel)):
            return Response(
                {'erreur': "Le code PIN actuel est incorrect."},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Changement effectif
        utilisateur.set_password(str(nouveau_pin))
        utilisateur.save(update_fields=['password'])

        return Response(
            {'message': "Code PIN modifié avec succès."},
            status=status.HTTP_200_OK
        )

    # ──────────────────────────────────────────────────────
    # 10. ACTIVATION DE COMPTE (lien d'invitation)
    # POST /api/membres/activation-compte/
    # Accès : public (AllowAny)
    # ──────────────────────────────────────────────────────

    @action(
        detail=False,
        methods=['post'],
        url_path='activation-compte',
        permission_classes=[AllowAny]
    )
    def activation_publique(self, request):
        token = request.data.get('token')
        pin = request.data.get('pin')

        if not token:
            return Response(
                {'erreur': "Le jeton d'activation est manquant."},
                status=status.HTTP_400_BAD_REQUEST
            )

        if not pin or not str(pin).isdigit() or len(str(pin)) != 4:
            return Response(
                {'erreur': "Le code PIN doit être un nombre de 4 chiffres."},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            utilisateur = Utilisateur.objects.get(token_invitation=token)
            utilisateur.set_password(pin)
            utilisateur.statut = 'actif'
            utilisateur.is_active = True
            utilisateur.token_invitation = None
            utilisateur.save()

            return Response(
                {'message': 'Votre compte a été activé avec succès !'},
                status=status.HTTP_200_OK
            )

        except Utilisateur.DoesNotExist:
            return Response(
                {'erreur': "Le lien d'activation est invalide ou a expiré."},
                status=status.HTTP_404_NOT_FOUND
            )
