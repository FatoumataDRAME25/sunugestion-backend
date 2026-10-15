from django.db import transaction
from django.db.models import Q, Sum
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from authentication.models import DUREE_VALIDITE_INVITATION, Utilisateur
from cotisations.models import Cotisation
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

# Fonctions du bureau occupées par une seule personne à la fois dans un GIE
# (le président est géré à part, par la passation de présidence)
FONCTIONS_UNIQUES = {
    'tresorier': 'trésorier',
    'secretaire': 'secrétaire',
}


class MembreViewSet(viewsets.ViewSet):
    """
    ViewSet du module Membres.

    Permissions par action :
    - list / retrieve            → EstMembreGIE (tout rôle GIE, admin exclu)
    - ajouter / analyser / importer → EstPresidentOuSecretaire
    - partial_update / changer_pin  → EstMembreGIE (propre profil uniquement)
    - modifier_role / modifier_fonction → EstPresident
    - renvoyer_invitation        → EstPresidentOuSecretaire
    - cotisations                → EstMembreGIE (membres du même GIE)
    - suspendre / reactiver      → EstPresident
    - activation_publique        → AllowAny
    """

    # Toujours permis, même si l'abonnement du groupement a expiré
    actions_autorisees_en_lecture_seule = {'partial_update', 'changer_pin'}

    def get_permissions(self):
        if self.action == 'activation_publique':
            return [AllowAny()]
        if self.action in ('ajouter', 'analyser_excel', 'importer', 'renvoyer_invitation'):
            return [EstPresidentOuSecretaire()]
        if self.action in ('modifier_role', 'modifier_fonction', 'suspendre', 'reactiver'):
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
        except (Utilisateur.DoesNotExist, ValueError, TypeError):
            # ValueError / TypeError : identifiant non numérique
            return None

    @staticmethod
    def _lire_role(valeur):
        """
        Retourne le rôle normalisé s'il est autorisé, sinon None.
        Toute valeur qui n'est pas une chaîne est refusée.
        """
        if not isinstance(valeur, str):
            return None

        role = valeur.strip().lower()

        return role if role in ROLES_AUTORISES else None

    @staticmethod
    def _compte_jamais_active(membre):
        """
        Vrai si le membre n'a jamais terminé son activation initiale
        (lien d'invitation) : statut en attente ou aucun PIN défini.
        """
        return (
            membre.statut == 'en_attente'
            or not membre.password
            or not membre.has_usable_password()
        )

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
                    token_expiration=timezone.now() + DUREE_VALIDITE_INVITATION,
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
    # PATCH /api/membres/membres/<id>/modifier-role/
    # Accès : président uniquement
    #
    # Règles :
    # - un GIE a toujours un président, et un seul ;
    # - le rôle « president » ne s'attribue que par une passation : le
    #   président en exercice indique son nouveau rôle (roleAncienPresident)
    #   et l'échange se fait dans une même transaction ;
    # - le président ne peut pas se rétrograder seul ;
    # - un seul trésorier et un seul secrétaire par GIE.
    # ──────────────────────────────────────────────────────

    @action(detail=True, methods=['patch'], url_path='modifier-role')
    def modifier_role(self, request, pk=None):
        gie = request.user.gie

        membre = self._get_membre_du_gie(pk, gie)
        if not membre:
            return Response(
                {'erreur': 'Membre introuvable.'},
                status=status.HTTP_404_NOT_FOUND
            )

        nouveau_role = self._lire_role(request.data.get('role'))
        if nouveau_role is None:
            return Response(
                {
                    'erreur': (
                        f"Rôle invalide. Valeurs autorisées : "
                        f"{', '.join(ROLES_AUTORISES)}."
                    )
                },
                status=status.HTTP_400_BAD_REQUEST
            )

        if nouveau_role == 'president':
            return self._passer_la_presidence(request, membre)

        if membre.id == request.user.id:
            return Response(
                {
                    'erreur': (
                        "Vous ne pouvez pas quitter la présidence sans la "
                        "transmettre. Attribuez le rôle de président à un "
                        "autre membre en indiquant votre nouveau rôle."
                    )
                },
                status=status.HTTP_400_BAD_REQUEST
            )

        if nouveau_role in FONCTIONS_UNIQUES and membre.statut == 'inactif':
            return Response(
                {
                    'erreur': (
                        "Un membre suspendu ne peut pas occuper une fonction "
                        "du bureau."
                    )
                },
                status=status.HTTP_400_BAD_REQUEST
            )

        with transaction.atomic():
            # Verrouille les membres du GIE pour la durée de l'opération
            membres_gie = {
                m.id: m
                for m in Utilisateur.objects.select_for_update().filter(gie=gie)
            }
            membre = membres_gie[membre.id]

            erreur = self._fonction_deja_occupee(
                membres_gie, nouveau_role, ignorer_ids={membre.id}
            )
            if erreur:
                return Response(
                    {'erreur': erreur},
                    status=status.HTTP_400_BAD_REQUEST
                )

            membre.role = nouveau_role
            membre.save(update_fields=['role'])

        return Response(
            {
                'message': f"Rôle mis à jour : {membre.prenom} {membre.nom} → {nouveau_role}.",
                'membre': MembreSerializer(membre).data,
            },
            status=status.HTTP_200_OK
        )

    @staticmethod
    def _fonction_deja_occupee(membres_gie, role, ignorer_ids):
        """
        Retourne un message d'erreur si la fonction unique `role` est déjà
        occupée par un autre membre du GIE, sinon None.
        """
        if role not in FONCTIONS_UNIQUES:
            return None

        for autre in membres_gie.values():
            if autre.role == role and autre.id not in ignorer_ids:
                return (
                    f"Le GIE a déjà un {FONCTIONS_UNIQUES[role]} "
                    f"({autre.prenom} {autre.nom}). Modifiez d'abord son rôle."
                )

        return None

    def _passer_la_presidence(self, request, membre):
        """
        Transmet la présidence à `membre`. L'ancien président reçoit le rôle
        fourni dans roleAncienPresident. Les deux changements sont faits
        dans la même transaction : le GIE n'est jamais sans président et
        n'en a jamais deux.
        """
        gie = request.user.gie

        if membre.id == request.user.id:
            return Response(
                {'erreur': 'Vous êtes déjà président.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Le parser camelCase convertit roleAncienPresident en snake_case
        role_ancien = self._lire_role(
            request.data.get(
                'role_ancien_president',
                request.data.get('roleAncienPresident')
            )
        )
        if role_ancien is None or role_ancien == 'president':
            return Response(
                {
                    'erreur': (
                        "Pour transmettre la présidence, indiquez le rôle que "
                        "vous occuperez ensuite (roleAncienPresident) : "
                        "tresorier, secretaire ou membre."
                    )
                },
                status=status.HTTP_400_BAD_REQUEST
            )

        with transaction.atomic():
            membres_gie = {
                m.id: m
                for m in Utilisateur.objects.select_for_update().filter(gie=gie)
            }
            ancien = membres_gie.get(request.user.id)
            nouveau = membres_gie.get(membre.id)

            if ancien is None or nouveau is None or ancien.role != 'president':
                return Response(
                    {'erreur': 'La passation ne peut pas être effectuée.'},
                    status=status.HTTP_403_FORBIDDEN
                )

            if nouveau.statut != 'actif':
                return Response(
                    {
                        'erreur': (
                            "Le nouveau président doit avoir un compte actif."
                        )
                    },
                    status=status.HTTP_400_BAD_REQUEST
                )

            autres_presidents = [
                m for m in membres_gie.values()
                if m.role == 'president' and m.id not in (ancien.id, nouveau.id)
            ]
            if autres_presidents:
                return Response(
                    {
                        'erreur': (
                            "Le GIE compte déjà un autre président. "
                            "Modifiez d'abord son rôle."
                        )
                    },
                    status=status.HTTP_400_BAD_REQUEST
                )

            # Le nouveau président libère sa fonction actuelle
            erreur = self._fonction_deja_occupee(
                membres_gie, role_ancien, ignorer_ids={ancien.id, nouveau.id}
            )
            if erreur:
                return Response(
                    {'erreur': erreur},
                    status=status.HTTP_400_BAD_REQUEST
                )

            nouveau.role = 'president'
            nouveau.save(update_fields=['role'])

            ancien.role = role_ancien
            ancien.save(update_fields=['role'])

        return Response(
            {
                'message': (
                    f"Présidence transmise à {nouveau.prenom} {nouveau.nom}. "
                    f"Votre nouveau rôle : {role_ancien}."
                ),
                'membre': MembreSerializer(nouveau).data,
                'ancien_president': MembreSerializer(ancien).data,
            },
            status=status.HTTP_200_OK
        )

    # ──────────────────────────────────────────────────────
    # 7 bis. MODIFIER LA FONCTION DANS LE BUREAU
    # PATCH /api/membres/membres/<id>/modifier-fonction/
    # Accès : président uniquement
    # Fonctions : vice_president, tresorier_adjoint, secretaire_adjoint,
    # ou "" pour retirer la fonction. Titre sans droit supplémentaire :
    # les permissions restent liées au rôle. Une seule personne par fonction.
    # ──────────────────────────────────────────────────────

    @action(detail=True, methods=['patch'], url_path='modifier-fonction')
    def modifier_fonction(self, request, pk=None):
        gie = request.user.gie

        membre = self._get_membre_du_gie(pk, gie)
        if not membre:
            return Response(
                {'erreur': 'Membre introuvable.'},
                status=status.HTTP_404_NOT_FOUND
            )

        fonctions = dict(Utilisateur.FONCTIONS_BUREAU)
        # Le parser camelCase convertit fonctionBureau en snake_case
        valeur = request.data.get('fonction_bureau', request.data.get('fonctionBureau'))
        fonction = valeur.strip().lower() if isinstance(valeur, str) else None

        if fonction is None or (fonction and fonction not in fonctions):
            return Response(
                {
                    'erreur': (
                        "Fonction invalide. Valeurs autorisées : "
                        f"{', '.join(fonctions)} ou une valeur vide pour la retirer."
                    )
                },
                status=status.HTTP_400_BAD_REQUEST
            )

        if fonction and membre.statut == 'inactif':
            return Response(
                {
                    'erreur': (
                        "Un membre suspendu ne peut pas occuper une fonction "
                        "du bureau."
                    )
                },
                status=status.HTTP_400_BAD_REQUEST
            )

        with transaction.atomic():
            if fonction:
                occupant = Utilisateur.objects.select_for_update().filter(
                    gie=gie, fonction_bureau=fonction
                ).exclude(id=membre.id).first()

                if occupant:
                    return Response(
                        {
                            'erreur': (
                                f"La fonction de {fonctions[fonction].lower()} est "
                                f"déjà occupée par {occupant.prenom} {occupant.nom}. "
                                f"Retirez-la-lui d'abord."
                            )
                        },
                        status=status.HTTP_400_BAD_REQUEST
                    )

            membre.fonction_bureau = fonction
            membre.save(update_fields=['fonction_bureau'])

        libelle = fonctions[fonction] if fonction else 'aucune'

        return Response(
            {
                'message': f"Fonction mise à jour : {membre.prenom} {membre.nom} → {libelle}.",
                'membre': MembreSerializer(membre).data,
            },
            status=status.HTTP_200_OK
        )

    # ──────────────────────────────────────────────────────
    # 7 ter. COTISATIONS D'UN MEMBRE
    # GET /api/membres/membres/<id>/cotisations/
    # Accès : tout membre du même GIE
    # ──────────────────────────────────────────────────────

    @action(detail=True, methods=['get'], url_path='cotisations')
    def cotisations(self, request, pk=None):
        membre = self._get_membre_du_gie(pk, request.user.gie)
        if not membre:
            return Response(
                {'erreur': 'Membre introuvable.'},
                status=status.HTTP_404_NOT_FOUND
            )

        aujourd_hui = timezone.localdate()

        cotisations = Cotisation.objects.filter(
            membre=membre
        ).select_related('session').order_by('-session__date_debut', '-id')

        # Mêmes règles de retard que le diagnostic financier
        en_retard = Q(statut='en_retard') | Q(
            statut='en_cours', session__date_fin__lt=aujourd_hui
        )
        en_cours = Q(statut='en_cours') & ~Q(session__date_fin__lt=aujourd_hui)

        def total(filtre):
            return cotisations.filter(filtre).aggregate(
                total=Sum('session__montant')
            )['total'] or 0

        lignes = []
        for cotisation in cotisations:
            if cotisation.statut == 'paye':
                statut = 'paye'
            elif (
                cotisation.statut == 'en_retard'
                or cotisation.session.date_fin < aujourd_hui
            ):
                statut = 'en_retard'
            else:
                statut = 'en_cours'

            lignes.append({
                'id': cotisation.id,
                'session': cotisation.session.libelle,
                'montant': cotisation.session.montant,
                'date_debut': cotisation.session.date_debut,
                'date_fin': cotisation.session.date_fin,
                'statut': statut,
                'date_paiement': cotisation.date_paiement,
                'mode_paiement': cotisation.mode_paiement,
            })

        return Response(
            {
                'cotisations': lignes,
                'total_paye': total(Q(statut='paye')),
                'total_en_retard': total(en_retard),
                'total_en_cours': total(en_cours),
                'nombre_payees': cotisations.filter(statut='paye').count(),
                'nombre_en_retard': cotisations.filter(en_retard).count(),
            },
            status=status.HTTP_200_OK
        )

    # ──────────────────────────────────────────────────────
    # 7 quater. RENVOYER L'INVITATION
    # POST /api/membres/membres/<id>/renvoyer-invitation/
    # Accès : président, secrétaire
    # Génère un nouveau lien (l'ancien ne fonctionne plus) valable 72 h.
    # ──────────────────────────────────────────────────────

    @action(detail=True, methods=['post'], url_path='renvoyer-invitation')
    def renvoyer_invitation(self, request, pk=None):
        membre = self._get_membre_du_gie(pk, request.user.gie)
        if not membre:
            return Response(
                {'erreur': 'Membre introuvable.'},
                status=status.HTTP_404_NOT_FOUND
            )

        if membre.statut != 'en_attente':
            return Response(
                {'erreur': "Ce membre a déjà activé son compte."},
                status=status.HTTP_400_BAD_REQUEST
            )

        membre.generer_token_invitation()

        from membres.utils import envoyer_invitation
        envoyer_invitation(membre)

        return Response(
            {
                'message': f"Invitation renvoyée à {membre.prenom} {membre.nom}.",
                'tokenInvitation': membre.token_invitation,
                'membre': MembreSerializer(membre).data,
            },
            status=status.HTTP_200_OK
        )

    # ──────────────────────────────────────────────────────
    # 8. SUSPENDRE UN MEMBRE
    # PATCH /api/membres/membres/<id>/suspendre/
    # Accès : président uniquement
    # Le président ne peut pas se suspendre lui-même, ni suspendre le
    # trésorier, ni suspendre un compte jamais activé.
    # is_active passe à False : les jetons déjà émis sont refusés par
    # l'authentification JWT, y compris au renouvellement.
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

        if membre.role == 'tresorier':
            return Response(
                {
                    'erreur': (
                        "Le trésorier ne peut pas être suspendu. "
                        "Modifiez d'abord son rôle."
                    )
                },
                status=status.HTTP_403_FORBIDDEN
            )

        if membre.statut == 'inactif':
            return Response(
                {'erreur': 'Ce membre est déjà suspendu.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        if self._compte_jamais_active(membre):
            return Response(
                {
                    'erreur': (
                        "Ce compte n'a jamais été activé : il ne peut pas "
                        "être suspendu."
                    )
                },
                status=status.HTTP_400_BAD_REQUEST
            )

        membre.statut = 'inactif'
        membre.is_active = False
        membre.save(update_fields=['statut', 'is_active'])

        return Response(
            {
                'message': f"{membre.prenom} {membre.nom} a été suspendu.",
                'membre': MembreSerializer(membre).data,
            },
            status=status.HTTP_200_OK
        )

    # ──────────────────────────────────────────────────────
    # 9. RÉACTIVER UN MEMBRE
    # PATCH /api/membres/membres/<id>/reactiver/
    # Accès : président uniquement
    # Ne remplace pas l'activation initiale par lien d'invitation.
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

        if self._compte_jamais_active(membre):
            return Response(
                {
                    'erreur': (
                        "Ce compte n'a jamais été activé. Le membre doit "
                        "d'abord l'activer avec son lien d'invitation."
                    )
                },
                status=status.HTTP_400_BAD_REQUEST
            )

        membre.statut = 'actif'
        membre.is_active = True
        membre.save(update_fields=['statut', 'is_active'])

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
        # Le parser camelCase convertit les clés reçues en snake_case
        pin_actuel = request.data.get('pin_actuel', request.data.get('pinActuel', ''))
        nouveau_pin = request.data.get('nouveau_pin', request.data.get('nouveauPin', ''))
        confirmation_pin = request.data.get('confirmation_pin', request.data.get('confirmationPin', ''))

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

            if utilisateur.invitation_expiree():
                return Response(
                    {
                        'erreur': (
                            "Ce lien d'activation a expiré. Demandez au "
                            "responsable de votre groupement de vous renvoyer "
                            "une invitation."
                        )
                    },
                    status=status.HTTP_400_BAD_REQUEST
                )

            utilisateur.set_password(pin)
            utilisateur.statut = 'actif'
            utilisateur.is_active = True
            utilisateur.token_invitation = None
            utilisateur.token_expiration = None
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
