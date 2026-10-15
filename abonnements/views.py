import logging

from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from authentication.models import GIE
from authentication.permissions import (
    EstAdministrateur,
    EstMembreGIE,
    EstPresidentOuTresorier,
)
from paiements.paydunya_service import (
    PayDunyaError,
    PayDunyaNetworkError,
    construire_url_annulation,
    construire_url_retour,
    creer_facture,
    verifier_facture,
)

from .models import PaiementAbonnement
from .serializers import (
    PaiementAbonnementSerializer,
    PaiementManuelSerializer,
    PayerAbonnementSerializer,
)
from .models import DELAI_GRACE_JOURS
from .services import (
    DUREE_ESSAI_JOURS,
    calculer_tarif,
    compter_membres_actifs,
    creer_paiement,
    grille_tarifaire,
    marquer_paiement_echoue,
    obtenir_abonnement,
    periode_suivante,
    valider_paiement,
)

logger = logging.getLogger(__name__)

ROLES_GESTION = ('president', 'tresorier')


def resume_abonnement(abonnement, avec_details):
    """
    Situation de l'abonnement d'un groupement. Les montants et l'historique
    ne sont ajoutés que pour le président, le trésorier et l'administrateur.
    """
    gie = abonnement.gie
    donnees = {
        'statut': abonnement.statut,
        'etat': abonnement.etat(),
        'date_debut': abonnement.date_debut,
        'date_fin': abonnement.date_fin,
        'jours_restants': abonnement.jours_restants(),
        'delai_grace_jours': abonnement.delai_grace(),
        'date_lecture_seule': abonnement.date_lecture_seule(),
    }

    if avec_details:
        nombre = compter_membres_actifs(gie)
        debut, fin = periode_suivante(abonnement)
        donnees.update({
            'membres_actifs': nombre,
            'tarif': calculer_tarif(nombre),
            'prochaine_periode': {'debut': debut, 'fin': fin},
            'grille': grille_tarifaire(),
            'paiements': PaiementAbonnementSerializer(
                abonnement.paiements.all()[:12], many=True
            ).data,
        })

    return donnees


# ─── Grille publique (page d'accueil) ─────────────────────────────────────────

class GrilleTarifaireView(APIView):
    """
    GET /api/abonnements/grille/
    Public : la page d'accueil affiche les tarifs à partir de la même grille
    que celle utilisée pour la facturation.
    """

    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request):
        donnees = grille_tarifaire()
        donnees.update({
            'duree_essai_jours': DUREE_ESSAI_JOURS,
            'delai_grace_jours': DELAI_GRACE_JOURS,
            'modes_paiement': ['Wave', 'Orange Money'],
        })
        return Response(donnees)


# ─── Espace du groupement ─────────────────────────────────────────────────────

class MonAbonnementView(APIView):
    """
    GET /api/abonnements/mon-abonnement/
    Tout membre voit l'état de l'abonnement (bandeau d'alerte) ;
    le président et le trésorier voient aussi le tarif et l'historique.
    """

    permission_classes = [EstMembreGIE]

    def get(self, request):
        abonnement = obtenir_abonnement(request.user.gie)
        donnees = resume_abonnement(
            abonnement, avec_details=request.user.role in ROLES_GESTION
        )
        donnees['peut_payer'] = request.user.role in ROLES_GESTION
        return Response(donnees, status=status.HTTP_200_OK)


class PayerAbonnementView(APIView):
    """
    POST /api/abonnements/payer/   { "modePaiement": "wave" | "orange_money" }
    Crée une facture PayDunya pour la période suivante. L'abonnement n'est
    prolongé qu'après confirmation du paiement par PayDunya.
    Permis même en lecture seule, puisque c'est la façon d'en sortir.
    """

    permission_classes = [EstPresidentOuTresorier]
    autorise_en_lecture_seule = True

    def post(self, request):
        serializer = PayerAbonnementSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        gie = request.user.gie
        paiement = creer_paiement(
            gie, serializer.validated_data['mode_paiement'], initie_par=request.user
        )

        try:
            facture = creer_facture(
                montant=int(paiement.montant),
                description=(
                    f"Abonnement SunuGestion — {gie.nom} "
                    f"({paiement.nombre_membres} membres actifs)"
                ),
                reference=f"ABONNEMENT-{paiement.id}",
                nom_client=f"{request.user.prenom} {request.user.nom}",
                telephone_client=request.user.telephone or '',
                return_url=construire_url_retour('abonnement', paiement.id),
                cancel_url=construire_url_annulation('abonnement', paiement.id),
            )
        except PayDunyaNetworkError as exc:
            marquer_paiement_echoue(paiement)
            return Response({'detail': str(exc)}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        except PayDunyaError as exc:
            marquer_paiement_echoue(paiement)
            return Response({'detail': str(exc)}, status=status.HTTP_502_BAD_GATEWAY)

        paiement.token_paydunya = facture['token']
        paiement.save(update_fields=['token_paydunya'])

        return Response(
            {
                'paiement_id': paiement.id,
                'montant': paiement.montant,
                'url_paiement': facture['url_paiement'],
            },
            status=status.HTTP_201_CREATED
        )


class PaiementAbonnementDetailView(APIView):
    """
    GET /api/abonnements/paiements/<id>/
    Statut d'un paiement (page de retour PayDunya). Si le paiement est encore
    en attente, PayDunya est interrogé directement, au cas où sa notification
    ne serait pas encore arrivée.
    """

    permission_classes = [EstPresidentOuTresorier]

    def get(self, request, pk):
        paiement = get_object_or_404(
            PaiementAbonnement, pk=pk, abonnement__gie=request.user.gie
        )

        if paiement.statut == 'en_attente' and paiement.token_paydunya:
            verifier_paiement_aupres_de_paydunya(paiement)
            paiement.refresh_from_db()

        return Response(PaiementAbonnementSerializer(paiement).data)


def verifier_paiement_aupres_de_paydunya(paiement):
    """
    Interroge PayDunya et valide (ou marque échoué) le paiement.
    Ne fait jamais confiance à une simple redirection : seul le statut
    renvoyé par PayDunya, avec le bon montant, valide le paiement.
    """
    try:
        verification = verifier_facture(paiement.token_paydunya)
    except (PayDunyaError, PayDunyaNetworkError) as exc:
        logger.warning("Abonnement — vérification PayDunya impossible : %s", exc)
        return None

    statut = verification['statut']

    if statut == 'completed':
        if int(verification['montant_confirme'] or 0) != int(paiement.montant):
            logger.error(
                "Abonnement — montant incohérent pour le paiement %s : attendu %s, reçu %s",
                paiement.id, paiement.montant, verification['montant_confirme'],
            )
            return None
        return valider_paiement(paiement)

    if statut in ('failed', 'cancelled'):
        marquer_paiement_echoue(paiement)

    return None


# ─── Espace administrateur ────────────────────────────────────────────────────

def ligne_instance(gie):
    abonnement = obtenir_abonnement(gie)
    nombre = compter_membres_actifs(gie)
    return {
        'id': gie.id,
        'nom': gie.nom,
        'code': gie.code,
        'region': gie.region,
        'statut_gie': gie.statut,
        'membres_actifs': nombre,
        'montant_mensuel': calculer_tarif(nombre)['montant'],
        'abonnement': {
            'statut': abonnement.statut,
            'etat': abonnement.etat(),
            'date_fin': abonnement.date_fin,
            'jours_restants': abonnement.jours_restants(),
        },
    }


class InstancesAdminView(APIView):
    """GET /api/abonnements/admin/instances/ — tous les groupements et leur abonnement."""

    permission_classes = [EstAdministrateur]

    def get(self, request):
        gies = GIE.objects.all().order_by('nom')
        return Response([ligne_instance(gie) for gie in gies])


class InstanceAdminDetailView(APIView):
    """GET /api/abonnements/admin/instances/<id>/ — abonnement et historique d'un groupement."""

    permission_classes = [EstAdministrateur]

    def get(self, request, pk):
        gie = get_object_or_404(GIE, pk=pk)
        donnees = ligne_instance(gie)
        donnees['abonnement'] = resume_abonnement(obtenir_abonnement(gie), avec_details=True)
        return Response(donnees)


class PaiementManuelAdminView(APIView):
    """
    POST /api/abonnements/admin/instances/<id>/paiement-manuel/  { "note": "..." }
    Action de secours : enregistre un paiement reçu hors PayDunya
    (espèces, incident…) et prolonge l'abonnement d'un mois.
    """

    permission_classes = [EstAdministrateur]

    def post(self, request, pk):
        gie = get_object_or_404(GIE, pk=pk)
        serializer = PaiementManuelSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        paiement = creer_paiement(
            gie, 'manuel',
            initie_par=request.user,
            note=serializer.validated_data.get('note', ''),
        )
        valider_paiement(paiement)
        paiement.refresh_from_db()

        return Response(
            {
                'paiement': PaiementAbonnementSerializer(paiement).data,
                'abonnement': resume_abonnement(obtenir_abonnement(gie), avec_details=False),
            },
            status=status.HTTP_201_CREATED
        )
