"""
Callback PayDunya pour SunuGestion.

Endpoint public appelé par PayDunya après chaque tentative de paiement.

Distingue trois types d'opérations :
- PAY-IN  cotisation          : COTISATION-<id>
- PAY-IN  remboursement prêt  : PRET-REMBOURSEMENT-<id>
- PAY-OUT décaissement prêt   : DECAISSEMENT-PRET-<id>  (via token_decaissement_paydunya)
"""

import logging

from django.db import transaction
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from cotisations.models import Cotisation
from historiques.models import HistoriqueOperation
from notifications.service import envoyer_notification
from paiements.paydunya_service import (
    PayDunyaError,
    PayDunyaNetworkError,
    verifier_facture,
    verifier_decaissement,
)
from prets.models import Pret
from authentication.models import Utilisateur
from prets.views import ajouter_mois

logger = logging.getLogger(__name__)


# ─── Helpers destinataires ────────────────────────────────────────────────────

def _tresoriers_actifs(gie):
    return Utilisateur.objects.filter(gie=gie, role='tresorier', statut='actif')


def _president_tresorier_actifs(gie):
    return Utilisateur.objects.filter(
        gie=gie, role__in=['president', 'tresorier'], statut='actif'
    )


# ─── Callback principal ───────────────────────────────────────────────────────

@csrf_exempt
@api_view(['POST'])
@permission_classes([AllowAny])
def paydunya_callback(request):
    """
    POST /api/paiements/paydunya/callback/

    Reçoit les notifications PayDunya pour PAY-IN et PAY-OUT.
    Ne fait jamais confiance au seul callback — vérifie toujours auprès de PayDunya.
    """
    data = request.data
    invoice_token = data.get('token') or data.get('invoice_token')

    if not invoice_token:
        logger.warning("Callback PayDunya reçu sans token.")
        return Response({'detail': 'Token manquant.'}, status=400)

    logger.info("Callback PayDunya reçu | token=%s...", invoice_token[:8])

    # ─── PAY-OUT : décaissement prêt ─────────────────────────────────────────
    pret_decaissement = Pret.objects.filter(
        token_decaissement_paydunya=invoice_token
    ).first()

    if pret_decaissement:
        return _traiter_callback_decaissement(pret_decaissement, invoice_token)

    # ─── PAY-IN : cotisation ──────────────────────────────────────────────────
    cotisation = Cotisation.objects.filter(token_paydunya=invoice_token).first()
    if cotisation:
        return _traiter_callback_payin(cotisation, invoice_token, type_objet='cotisation')

    # ─── PAY-IN : remboursement prêt ──────────────────────────────────────────
    pret_remboursement = Pret.objects.filter(token_paydunya=invoice_token).first()
    if pret_remboursement:
        return _traiter_callback_payin(pret_remboursement, invoice_token, type_objet='remboursement_pret')

    logger.warning("Callback PayDunya — token inconnu : %s...", invoice_token[:8])
    return Response({'detail': 'Token inconnu.'}, status=200)


# ─── PAY-IN handler ───────────────────────────────────────────────────────────

def _traiter_callback_payin(objet, invoice_token, type_objet):
    """Vérifie et valide un PAY-IN (cotisation ou remboursement prêt)."""
    try:
        verification = verifier_facture(invoice_token)
    except PayDunyaNetworkError as exc:
        logger.error("Callback PAY-IN — erreur réseau : %s", exc)
        return Response({'detail': 'Erreur réseau PayDunya.'}, status=503)
    except PayDunyaError as exc:
        logger.error("Callback PAY-IN — erreur PayDunya : %s", exc)
        return Response({'detail': str(exc)}, status=502)

    statut = verification['statut']
    montant_confirme = verification['montant_confirme']

    logger.info("Callback PAY-IN — statut=%s | montant=%s", statut, montant_confirme)

    if statut != 'completed':
        return Response({'statut': statut}, status=200)

    if type_objet == 'cotisation':
        return _valider_cotisation(objet, montant_confirme)
    else:
        return _valider_remboursement_pret(objet, montant_confirme)


# ─── PAY-OUT handler ──────────────────────────────────────────────────────────

def _traiter_callback_decaissement(pret, disburse_token):
    """Vérifie et valide un PAY-OUT (décaissement prêt)."""
    try:
        verification = verifier_decaissement(disburse_token)
    except PayDunyaNetworkError as exc:
        logger.error("Callback PAY-OUT — erreur réseau : %s", exc)
        return Response({'detail': 'Erreur réseau PayDunya.'}, status=503)
    except PayDunyaError as exc:
        logger.error("Callback PAY-OUT — erreur PayDunya : %s", exc)
        return Response({'detail': str(exc)}, status=502)

    statut = verification['statut']
    montant_confirme = verification['montant_confirme']

    logger.info("Callback PAY-OUT — statut=%s | montant=%s", statut, montant_confirme)

    if statut != 'success':
        logger.info("Callback PAY-OUT — décaissement non réussi (%s), aucune action.", statut)
        return Response({'statut': statut}, status=200)

    return _valider_decaissement(pret, montant_confirme)


# ─── Validation cotisation ────────────────────────────────────────────────────

def _valider_cotisation(cotisation, montant_confirme):
    if cotisation.statut == 'paye':
        logger.info("Callback — cotisation %s déjà payée, ignoré.", cotisation.id)
        return Response({'statut': 'already_processed'}, status=200)

    montant_attendu = int(cotisation.session.montant)
    if montant_confirme != montant_attendu:
        logger.error(
            "Callback — montant incohérent cotisation %s : attendu %s, reçu %s",
            cotisation.id, montant_attendu, montant_confirme,
        )
        return Response({'detail': 'Montant incohérent.'}, status=400)

    with transaction.atomic():
        cotisation = Cotisation.objects.select_for_update().get(pk=cotisation.pk)
        if cotisation.statut == 'paye':
            return Response({'statut': 'already_processed'}, status=200)

        cotisation.statut = 'paye'
        cotisation.date_paiement = timezone.now()
        cotisation.save(update_fields=['statut', 'date_paiement'])

        HistoriqueOperation.objects.create(
            gie=cotisation.membre.gie,
            type_operation='entree',
            montant=cotisation.session.montant,
            libelle=(
                f'Paiement cotisation ({cotisation.mode_paiement}) - '
                f'{cotisation.membre.prenom} {cotisation.membre.nom} - '
                f'{cotisation.session.libelle}'
            ),
            cotisation=cotisation,
        )

    tresoriers = _tresoriers_actifs(cotisation.membre.gie)
    if tresoriers.exists():
        envoyer_notification(
            destinataires=tresoriers,
            titre='Paiement de cotisation reçu',
            message=(
                f'{cotisation.membre.prenom} {cotisation.membre.nom} '
                f'a payé sa cotisation pour la session '
                f'« {cotisation.session.libelle} ».'
            ),
            type_evenement='cotisation_payee_par_membre',
            module='cotisations',
            objet_id=cotisation.id,
        )

    logger.info("Callback — cotisation %s validée.", cotisation.id)
    return Response({'statut': 'completed'}, status=200)


# ─── Validation remboursement prêt ────────────────────────────────────────────

def _valider_remboursement_pret(pret, montant_confirme):
    if pret.statut == 'rembourse':
        logger.info("Callback — prêt %s déjà remboursé, ignoré.", pret.id)
        return Response({'statut': 'already_processed'}, status=200)

    montant_attendu = int(pret.montant)
    if montant_confirme != montant_attendu:
        logger.error(
            "Callback — montant incohérent remboursement prêt %s : attendu %s, reçu %s",
            pret.id, montant_attendu, montant_confirme,
        )
        return Response({'detail': 'Montant incohérent.'}, status=400)

    with transaction.atomic():
        pret = Pret.objects.select_for_update().get(pk=pret.pk)
        if pret.statut == 'rembourse':
            return Response({'statut': 'already_processed'}, status=200)

        pret.date_remboursement = timezone.now().date()
        pret.statut = 'rembourse'
        pret.save(update_fields=['statut', 'date_remboursement'])

        HistoriqueOperation.objects.create(
            gie=pret.membre.gie,
            type_operation='entree',
            montant=pret.montant,
            libelle=(
                f'Remboursement prêt ({pret.mode_paiement}) - '
                f'{pret.membre.prenom} {pret.membre.nom}'
            ),
            pret=pret,
        )

    destinataires = _president_tresorier_actifs(pret.membre.gie)
    if destinataires.exists():
        envoyer_notification(
            destinataires=destinataires,
            titre='Prêt remboursé',
            message=(
                f'{pret.membre.prenom} {pret.membre.nom} '
                f'a remboursé son prêt de {pret.montant} FCFA.'
            ),
            type_evenement='pret_rembourse',
            module='prets',
            objet_id=pret.id,
        )

    logger.info("Callback — remboursement prêt %s validé.", pret.id)
    return Response({'statut': 'completed'}, status=200)


# ─── Validation décaissement prêt (PAY-OUT) ───────────────────────────────────

def _valider_decaissement(pret, montant_confirme):
    """
    Valide le décaissement d'un prêt après confirmation SUCCESS PayDunya.
    Idempotent : si déjà en_cours, on retourne 200 sans rien faire.
    """
    if pret.statut == 'en_cours':
        logger.info("Callback PAY-OUT — prêt %s déjà décaissé, ignoré.", pret.id)
        return Response({'statut': 'already_processed'}, status=200)

    if pret.statut != 'approuve':
        logger.warning(
            "Callback PAY-OUT — prêt %s dans un statut inattendu : %s",
            pret.id, pret.statut,
        )
        return Response({'detail': f'Statut inattendu : {pret.statut}.'}, status=400)

    montant_attendu = int(pret.montant)
    if montant_confirme != montant_attendu:
        logger.error(
            "Callback PAY-OUT — montant incohérent prêt %s : attendu %s, reçu %s",
            pret.id, montant_attendu, montant_confirme,
        )
        return Response({'detail': 'Montant incohérent.'}, status=400)

    with transaction.atomic():
        pret = Pret.objects.select_for_update().get(pk=pret.pk)

        # Double vérification dans la transaction
        if pret.statut == 'en_cours':
            return Response({'statut': 'already_processed'}, status=200)

        date_decaissement = timezone.now().date()
        date_echeance = ajouter_mois(date_decaissement, pret.duree_mois)

        pret.date_echeance = date_echeance
        pret.statut = 'en_cours'
        pret.save(update_fields=['statut', 'date_echeance'])

        HistoriqueOperation.objects.create(
            gie=pret.membre.gie,
            type_operation='sortie',
            montant=pret.montant,
            libelle=(
                f'Décaissement prêt ({pret.mode_paiement}) - '
                f'{pret.membre.prenom} {pret.membre.nom}'
            ),
            pret=pret,
        )

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

    logger.info("Callback PAY-OUT — prêt %s décaissé avec succès.", pret.id)
    return Response({'statut': 'success'}, status=200)
