from django.utils import timezone
from rest_framework.permissions import IsAuthenticated
from datetime import date
import calendar
from django.shortcuts import get_object_or_404
from django.db.models import Q
from django.contrib.auth import get_user_model
from rest_framework.response import Response
from rest_framework import generics
from rest_framework.exceptions import ValidationError
from django.db import transaction
from historiques.views import calculer_solde
from historiques.models import HistoriqueOperation
from notifications.service import envoyer_notification
from authentication.permissions import EstMembreGIE, EstPresident, EstPresidentOuTresorier, EstTresorier
from paiements.paydunya_service import (
    creer_facture,
    initier_decaissement,
    soumettre_decaissement,
    PayDunyaError,
    PayDunyaNetworkError,
    _RETURN_URL,
)

from .models import ReglePret, Pret
from cotisations.models import Cotisation
from .serializers import (
    ReglePretSerializer,
    PretSerializer,
    PretApprobationSerializer,
    PretDecaissementSerializer,
    PretRemboursementSerializer,
)

Utilisateur = get_user_model()

MODES_ELECTRONIQUES = {'wave', 'orange_money'}


def _membres_actifs_roles(gie, roles, exclure_ids=None):
    """Retourne les membres actifs du GIE ayant un des rôles donnés."""
    qs = Utilisateur.objects.filter(
        gie=gie,
        role__in=roles,
        statut='actif'
    )
    if exclure_ids:
        qs = qs.exclude(id__in=exclure_ids)
    return qs


def ajouter_mois(date_depart, nombre_mois):

    mois_total = date_depart.month - 1 + nombre_mois

    annee = date_depart.year + mois_total // 12

    mois = mois_total % 12 + 1

    jour = min(
        date_depart.day,
        calendar.monthrange(annee, mois)[1]
    )

    return date(
        annee,
        mois,
        jour
    )

class ReglePretView(generics.GenericAPIView):
    serializer_class = ReglePretSerializer

    def get_permissions(self):
        # Lecture : tout membre GIE (admin exclu)
        # Création / modification : président uniquement
        if self.request.method in ('POST', 'PATCH'):
            return [EstPresident()]
        return [EstMembreGIE()]

    def get(self, request):
        try:
            regle = ReglePret.objects.get(
                gie=request.user.gie
            )
        except ReglePret.DoesNotExist:
            return Response(
                {"message": "Les règles de prêt ne sont pas encore configurées."},
                status=404
            )

        serializer = self.get_serializer(regle)
        return Response(serializer.data)


    def post(self, request):
        if ReglePret.objects.filter(gie=request.user.gie).exists():
            raise ValidationError(
                "Les règles de prêt de ce GIE existent déjà."
            )

        serializer = self.get_serializer(data=request.data)

        serializer.is_valid(raise_exception=True)

        serializer.save(
            gie=request.user.gie
        )

        return Response(
            serializer.data,
            status=201
        )

    def patch(self, request):
        try:
            regle = ReglePret.objects.get(
                gie=request.user.gie
            )
        except ReglePret.DoesNotExist:
            return Response(
                {"message": "Les règles de prêt n'existent pas encore."},
                status=404
            )

        serializer = self.get_serializer(
            regle,
            data=request.data,
            partial=True
        )

        serializer.is_valid(raise_exception=True)

        serializer.save(
            gie=request.user.gie
        )

        return Response(serializer.data)



class PretView(generics.GenericAPIView):

    serializer_class = PretSerializer
    permission_classes = [EstMembreGIE]

    def post(self, request):

        gie = request.user.gie

        # Vérifier que les règles de prêt existent
        try:
            regle = ReglePret.objects.get(
                gie=gie
            )
        except ReglePret.DoesNotExist:

            return Response(
                {
                    'message': (
                        'Les règles de prêt de ce GIE '
                        'ne sont pas encore configurées.'
                    )
                },
                status=404
            )

        # Valider les données de la demande
        serializer = self.get_serializer(
            data=request.data
        )

        serializer.is_valid(
            raise_exception=True
        )

        montant = serializer.validated_data['montant']

        # Vérifier le montant maximum autorisé
        if montant > regle.montant_max:

            raise ValidationError(
                {
                    'montant': (
                        f'Le montant maximum autorisé est '
                        f'{regle.montant_max} FCFA.'
                    )
                }
            )

        # Récupérer le solde actuel de la caisse
        _, _, solde = calculer_solde(gie)

        # Vérifier que le prêt ne dépasse pas le solde
        if montant > solde:

            raise ValidationError(
                {
                    'montant': (
                        'Le montant demandé est supérieur '
                        'au solde disponible de la caisse.'
                    )
                }
            )

        # Vérifier le nombre de prêts simultanés
        nombre_prets = Pret.objects.filter(
            membre=request.user,
            statut__in=['en_attente', 'en_cours', 'approuve']
        ).count()

        if nombre_prets >= regle.nombre_prets_simultanes:

            raise ValidationError(
                {
                    'pret': (
                        'Vous avez deja un prêt non rembourse.'
                    )
                }
            )

        # Vérifier que les cotisations sont à jour
        if regle.cotisation_a_jour_obligatoire:

            cotisation_impayee = Cotisation.objects.filter(
                membre=request.user,
                statut__in=['en_cours', 'en_retard']
            ).exists()

            if cotisation_impayee:

                raise ValidationError(
                    {
                        'cotisation': (
                            'Vous devez être à jour de vos cotisations '
                            'pour demander un prêt.'
                        )
                    }
                )

        # Créer la demande
        pret = serializer.save(
            membre=request.user,
            statut='en_attente'
        )

        # Notifier président + trésorier (sauf le demandeur lui-même)
        envoyer_notification(
            destinataires=_membres_actifs_roles(
                gie=gie,
                roles=['president', 'tresorier'],
                exclure_ids=[request.user.id],
            ),
            titre="Nouvelle demande de prêt",
            message=(
                f"{request.user.prenom} {request.user.nom} "
                f"a soumis une demande de prêt de {pret.montant} FCFA."
            ),
            type_evenement="demande_pret",
            module="prets",
            objet_id=pret.id,
        )

        return Response(
            serializer.data,
            status=201
        )


    def get(self, request, pk=None):

        gie = request.user.gie

        # Si un ID est fourni → détail du prêt
        if pk:

            pret = get_object_or_404(
                Pret,
                id=pk,
                membre__gie=gie
            )

            serializer = self.get_serializer(pret)

            return Response(
                serializer.data,
                status=200
            )

        # Sinon → liste de tous les prêts du GIE
        prets = Pret.objects.filter(
            membre__gie=gie
        )

        serializer = self.get_serializer(
            prets,
            many=True
        )

        return Response(
            serializer.data,
            status=200
        )

class PretApprobationView(generics.GenericAPIView):

    serializer_class = PretApprobationSerializer
    permission_classes = [EstPresident]

    def post(self, request, pk):

        try:
            pret = Pret.objects.get(
                id=pk
            )
        except Pret.DoesNotExist:
            return Response(
                {
                    'message': 'Ce prêt n existe pas.'
                },
                status=404
            )

        # Vérifier que le prêt est encore en attente
        if pret.statut != 'en_attente':

            raise ValidationError(
                {
                    'pret': (
                        'Ce prêt ne peut plus être approuvé.'
                    )
                }
            )

        # Récupérer les règles du GIE
        gie = pret.membre.gie

        try:
            regle = ReglePret.objects.get(
                gie=gie
            )
        except ReglePret.DoesNotExist:

            return Response(
                {
                    'message': (
                        'Les règles de prêt de ce GIE '
                        'ne sont pas configurées.'
                    )
                },
                status=404
            )

        # Valider la durée envoyée par le président
        serializer = self.get_serializer(
            data=request.data
        )

        serializer.is_valid(
            raise_exception=True
        )

        duree_mois = serializer.validated_data['duree_mois']

        # Vérifier la durée maximale
        if duree_mois > regle.duree_max_mois:

            raise ValidationError(
                {
                    'duree_mois': (
                        f'La durée maximale autorisée est de '
                        f'{regle.duree_max_mois} mois.'
                    )
                }
            )

        # Vérifier à nouveau le solde de la caisse
        _, _, solde = calculer_solde(gie)

        if pret.montant > solde:

            raise ValidationError(
                {
                    'pret': (
                        'Le solde disponible de la caisse '
                        'ne permet plus d approuver ce prêt.'
                    )
                }
            )

        pret.duree_mois = duree_mois
        pret.date_approbation = timezone.now()
        pret.statut = 'approuve'
        pret.save()

        # Notifier le demandeur + les trésoriers actifs du GIE
        # Le trésorier reçoit toujours la notif (il doit effectuer le décaissement)
        destinataires = Utilisateur.objects.filter(
            gie=gie,
            statut='actif'
        ).filter(
            Q(id=pret.membre.id) | Q(role='tresorier')
        ).distinct()

        envoyer_notification(
            destinataires=destinataires,
            titre="Prêt approuvé",
            message=(
                f"Le prêt de {pret.montant} FCFA de "
                f"{pret.membre.prenom} {pret.membre.nom} a été approuvé."
            ),
            type_evenement="pret_approuve",
            module="prets",
            objet_id=pret.id,
        )

        return Response(PretSerializer(pret).data, status=200)


class PretDecaissementView(generics.GenericAPIView):

    serializer_class = PretDecaissementSerializer
    permission_classes = [EstTresorier]

    def post(self, request, pk):

        try:
            pret = Pret.objects.get(id=pk)
        except Pret.DoesNotExist:
            return Response({'message': 'Ce prêt n existe pas.'}, status=404)

        if pret.statut != 'approuve':
            raise ValidationError(
                {'pret': 'Seul un prêt approuvé peut être décaissé.'}
            )

        gie = pret.membre.gie

        _, _, solde = calculer_solde(gie)
        if pret.montant > solde:
            raise ValidationError(
                {'pret': 'Le solde disponible de la caisse ne permet pas de décaisser ce prêt.'}
            )

        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        mode_paiement = serializer.validated_data['mode_paiement']

        # ─── Décaissement électronique (Pay-out PayDunya) ─────────────────────
        if mode_paiement in MODES_ELECTRONIQUES:
            return self._initier_decaissement_electronique(pret, mode_paiement)

        # ─── Décaissement en espèces — comportement inchangé ──────────────────
        return self._decaissement_especes(pret, mode_paiement)

    def _initier_decaissement_electronique(self, pret, mode_paiement):
        """
        Initie un Pay-out PayDunya vers le téléphone du membre.
        Le prêt N'est PAS marqué comme en_cours ici.
        Il le sera uniquement après confirmation SUCCESS par PayDunya.
        """
        membre = pret.membre
        reference = f"DECAISSEMENT-PRET-{pret.id}"

        # Supprimer l'indicatif pays si présent (ex: +221771234567 → 771234567)
        telephone = (membre.telephone or '').lstrip('+').lstrip('221')

        try:
            # Étape 1 : obtenir le disburse_token
            resultat_init = initier_decaissement(
                montant=int(pret.montant),
                telephone_beneficiaire=telephone,
                mode_paiement=mode_paiement,
                reference=reference,
            )

            disburse_token = resultat_init.get('disburse_token')
            if not disburse_token:
                raise PayDunyaError("Token de décaissement absent dans la réponse PayDunya.")

            # Étape 2 : soumettre la facture
            resultat_soumission = soumettre_decaissement(
                disburse_token=disburse_token,
                disburse_id=reference,
            )

        except PayDunyaNetworkError as exc:
            return Response({'detail': str(exc)}, status=503)
        except PayDunyaError as exc:
            return Response({'detail': str(exc)}, status=502)

        # Sauvegarder le token de décaissement et le mode sans encore marquer en_cours
        pret.mode_paiement = mode_paiement
        pret.token_decaissement_paydunya = disburse_token
        pret.save(update_fields=['mode_paiement', 'token_decaissement_paydunya'])

        statut_soumission = resultat_soumission.get('status', 'created')

        return Response(
            {
                'statut': 'en_attente_decaissement',
                'statut_paydunya': statut_soumission,
                'mode_paiement': mode_paiement,
                'disburse_token': disburse_token,
                'pret': PretSerializer(pret).data,
            },
            status=200
        )

    @transaction.atomic
    def _decaissement_especes(self, pret, mode_paiement):
        """Décaissement en espèces — comportement original inchangé."""
        pret = Pret.objects.select_for_update().get(pk=pret.pk)

        HistoriqueOperation.objects.create(
            gie=pret.membre.gie,
            type_operation='sortie',
            montant=pret.montant,
            libelle=f'Décaissement du prêt de {pret.membre}',
            pret=pret,
        )

        date_decaissement = timezone.now().date()
        date_echeance = ajouter_mois(date_decaissement, pret.duree_mois)

        pret.mode_paiement = mode_paiement
        pret.date_echeance = date_echeance
        pret.statut = 'en_cours'
        pret.save()

        envoyer_notification(
            destinataires=[pret.membre],
            titre="Prêt décaissé",
            message=(
                f"Votre prêt de {pret.montant} FCFA a été décaissé. "
                f"Date d'échéance : {pret.date_echeance}."
            ),
            type_evenement="pret_decaisse",
            module="prets",
            objet_id=pret.id,
        )

        return Response(PretSerializer(pret).data, status=200)


class PretRemboursementView(generics.GenericAPIView):

    serializer_class = PretRemboursementSerializer
    permission_classes = [EstMembreGIE]

    def post(self, request, pk):

        try:
            pret = Pret.objects.get(id=pk)
        except Pret.DoesNotExist:
            return Response({'message': 'Ce prêt n existe pas.'}, status=404)

        if pret.statut != 'en_cours':
            raise ValidationError(
                {'pret': 'Seul un prêt en cours peut être remboursé.'}
            )

        # Vérification : seul le membre concerné ou le trésorier peut rembourser
        est_tresorier = request.user.role == 'tresorier'
        est_membre_concerne = request.user == pret.membre

        if not est_membre_concerne and not est_tresorier:
            return Response(
                {'detail': "Vous n'êtes pas autorisé à effectuer ce remboursement."},
                status=403
            )

        serializer = self.get_serializer(data=request.data, context={
            'request': request,
            'pret': pret,
        })
        serializer.is_valid(raise_exception=True)

        mode_paiement = serializer.validated_data['mode_paiement']

        # ─── Remboursement électronique (Wave ou Orange Money) ────────────────
        if mode_paiement in MODES_ELECTRONIQUES:
            return self._initier_remboursement_electronique(pret, mode_paiement)

        # ─── Remboursement en espèces — comportement inchangé ─────────────────
        return self._remboursement_especes(request, pret, mode_paiement)

    def _initier_remboursement_electronique(self, pret, mode_paiement):
        """
        Crée une facture PayDunya pour le remboursement.
        Le prêt N'est PAS marqué comme remboursé ici.
        Il le sera uniquement après confirmation COMPLETED par PayDunya.
        """
        membre = pret.membre
        reference = f"PRET-REMBOURSEMENT-{pret.id}"

        try:
            resultat = creer_facture(
                montant=int(pret.montant),
                description=(
                    f"Remboursement prêt — {pret.montant} FCFA "
                    f"({membre.prenom} {membre.nom})"
                ),
                reference=reference,
                nom_client=f"{membre.prenom} {membre.nom}",
                telephone_client=membre.telephone or '',
                return_url=(
                    f"{_RETURN_URL}"
                    f"?type=pret"
                    f"&id={pret.id}"
                ),
            )
        except PayDunyaNetworkError as exc:
            return Response(
                {'detail': str(exc)},
                status=503
            )
        except PayDunyaError as exc:
            return Response(
                {'detail': str(exc)},
                status=502
            )

        # Sauvegarder le token et le mode sans marquer comme remboursé
        pret.mode_paiement = mode_paiement
        pret.token_paydunya = resultat['token']
        pret.save(update_fields=['mode_paiement', 'token_paydunya'])

        return Response(
            {
                'statut': 'en_attente_paiement',
                'mode_paiement': mode_paiement,
                'token': resultat['token'],
                'urlPaiement': resultat['url_paiement'],
                'pret': PretSerializer(pret).data,
            },
            status=200
        )

    @transaction.atomic
    def _remboursement_especes(self, request, pret, mode_paiement):
        """
        Enregistre directement le remboursement en espèces.
        Comportement identique à l'original.
        """
        pret = Pret.objects.select_for_update().get(pk=pret.pk)

        HistoriqueOperation.objects.create(
            gie=pret.membre.gie,
            type_operation='entree',
            montant=pret.montant,
            libelle=f'Remboursement du prêt de {pret.membre}',
            pret=pret,
        )

        pret.date_remboursement = timezone.now().date()
        pret.statut = 'rembourse'
        pret.mode_paiement = mode_paiement
        pret.save()

        envoyer_notification(
            destinataires=_membres_actifs_roles(
                gie=pret.membre.gie,
                roles=['president', 'tresorier'],
                exclure_ids=[request.user.id],
            ),
            titre="Prêt remboursé",
            message=(
                f"{pret.membre.prenom} {pret.membre.nom} "
                f"a remboursé son prêt de {pret.montant} FCFA."
            ),
            type_evenement="pret_rembourse",
            module="prets",
            objet_id=pret.id,
        )

        return Response(PretSerializer(pret).data, status=200)
