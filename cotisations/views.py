from rest_framework import generics
from django.db import transaction
from django.utils import timezone
from rest_framework import generics, status
from rest_framework.response import Response
from cotisations.models import Cotisation, SessionCotisation
from historiques.models import HistoriqueOperation
from .serializers import CotisationPaiementSerializer, CotisationSerializer, SessionCotisationSerializer
from notifications.service import envoyer_notification
from authentication.models import Utilisateur
from paiements.paydunya_service import (
    creer_facture,
    PayDunyaError,
    PayDunyaNetworkError,
)

# Modes qui déclenchent un paiement électronique via PayDunya
MODES_ELECTRONIQUES = {'wave', 'orange_money'}


class SessionCotisationCreateView(generics.ListCreateAPIView):

    serializer_class = SessionCotisationSerializer

    def get_queryset(self):
        return SessionCotisation.objects.filter(
            createur__gie=self.request.user.gie
        )

    def perform_create(self, serializer):
        session = serializer.save(createur=self.request.user)

        # Notifier les membres qui ont une cotisation dans cette session
        destinataires = Utilisateur.objects.filter(
            cotisations__session=session
        ).distinct()

        if destinataires.exists():
            envoyer_notification(
                destinataires=destinataires,
                titre='Nouvelle session de cotisation',
                message=f'La session « {session.libelle} » vient d\'être ouverte.',
                type_evenement='nouvelle_session_cotisation',
                module='cotisations',
                objet_id=session.id,
            )


class CotisationListView(generics.ListAPIView):
    serializer_class = CotisationSerializer

    def get_queryset(self):
        session_id = self.kwargs['session_id']

        return Cotisation.objects.filter(
            session_id=session_id
        )


class CotisationPaiementView(generics.GenericAPIView):

    serializer_class = CotisationPaiementSerializer

    def post(self, request, pk):

        cotisation = Cotisation.objects.get(pk=pk)

        if cotisation.statut == 'paye':
            return Response(
                {'detail': 'Cette cotisation a déjà été payée.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        serializer = self.get_serializer(data=request.data, context={
            'request': request,
            'cotisation': cotisation,
        })
        serializer.is_valid(raise_exception=True)

        mode_paiement = serializer.validated_data['mode_paiement']

        # ─── Paiement électronique (Wave ou Orange Money) ─────────────────────
        if mode_paiement in MODES_ELECTRONIQUES:
            return self._initier_paiement_electronique(cotisation, mode_paiement)

        # ─── Paiement en espèces — comportement inchangé ──────────────────────
        return self._paiement_especes(request, cotisation, mode_paiement)

    # ─────────────────────────────────────────────────────────────────────────
    # Paiement électronique via PayDunya
    # ─────────────────────────────────────────────────────────────────────────

    def _initier_paiement_electronique(self, cotisation, mode_paiement):
        """
        Crée une facture PayDunya et retourne l'URL de paiement au frontend.
        La cotisation N'EST PAS marquée comme payée ici.
        Elle le sera uniquement après confirmation PayDunya (prochaine étape).
        """
        membre = cotisation.membre

        # Référence unique identifiant cette cotisation dans PayDunya
        reference = f"cotisation-{cotisation.id}"

        try:
            resultat = creer_facture(
                montant=int(cotisation.session.montant),
                description=(
                    f"Cotisation — {cotisation.session.libelle} "
                    f"({membre.prenom} {membre.nom})"
                ),
                reference=reference,
                nom_client=f"{membre.prenom} {membre.nom}",
                telephone_client=membre.telephone or '',
            )
        except PayDunyaNetworkError as exc:
            return Response(
                {'detail': str(exc)},
                status=status.HTTP_503_SERVICE_UNAVAILABLE
            )
        except PayDunyaError as exc:
            return Response(
                {'detail': str(exc)},
                status=status.HTTP_502_BAD_GATEWAY
            )

        # Sauvegarder le mode de paiement et le token PayDunya sur la cotisation
        # sans changer le statut — le paiement n'est pas encore confirmé
        cotisation.mode_paiement = mode_paiement
        cotisation.token_paydunya = resultat['token']
        cotisation.save(update_fields=['mode_paiement', 'token_paydunya'])

        return Response(
            {
                'statut': 'en_attente_paiement',
                'mode_paiement': mode_paiement,
                'token': resultat['token'],
                'urlPaiement': resultat['url_paiement'],
                'cotisation': CotisationSerializer(cotisation).data,
            },
            status=status.HTTP_200_OK
        )

    # ─────────────────────────────────────────────────────────────────────────
    # Paiement en espèces — comportement original inchangé
    # ─────────────────────────────────────────────────────────────────────────

    @transaction.atomic
    def _paiement_especes(self, request, cotisation, mode_paiement):
        """
        Enregistre directement le paiement en espèces.
        Comportement identique à l'original.
        """
        cotisation = Cotisation.objects.select_for_update().get(pk=cotisation.pk)

        cotisation.statut = 'paye'
        cotisation.mode_paiement = mode_paiement
        cotisation.date_paiement = timezone.now()
        cotisation.save()

        HistoriqueOperation.objects.create(
            gie=cotisation.membre.gie,
            type_operation='entree',
            montant=cotisation.session.montant,
            libelle=(
                f'Paiement cotisation - '
                f'{cotisation.membre.prenom} {cotisation.membre.nom} - '
                f'{cotisation.session.libelle}'
            ),
            cotisation=cotisation
        )

        # Notification selon qui effectue le paiement
        paye_pour_soi = (request.user == cotisation.membre)

        if not paye_pour_soi:
            envoyer_notification(
                destinataires=[cotisation.membre],
                titre='Cotisation enregistrée',
                message=(
                    f'Votre cotisation pour la session « {cotisation.session.libelle} » '
                    f'a été enregistrée par le trésorier.'
                ),
                type_evenement='cotisation_payee_par_tresorier',
                module='cotisations',
                objet_id=cotisation.id,
            )
        else:
            tresoriers = Utilisateur.objects.filter(
                gie=cotisation.membre.gie,
                role='tresorier',
                statut='actif',
            )
            if tresoriers.exists():
                envoyer_notification(
                    destinataires=tresoriers,
                    titre='Paiement de cotisation reçu',
                    message=(
                        f'{cotisation.membre.prenom} {cotisation.membre.nom} '
                        f'a payé sa cotisation pour la session « {cotisation.session.libelle} ».'
                    ),
                    type_evenement='cotisation_payee_par_membre',
                    module='cotisations',
                    objet_id=cotisation.id,
                )

        return Response(
            CotisationSerializer(cotisation).data,
            status=status.HTTP_200_OK
        )
