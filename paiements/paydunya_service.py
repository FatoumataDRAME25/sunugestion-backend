"""
Service PayDunya pour SunuGestion.

Responsabilité :
- créer une facture PayDunya pour les paiements entrants (Pay-in)
- vérifier le statut d'une facture
- initier un décaissement (Pay-out)
- soumettre un décaissement
- vérifier le statut d'un décaissement

Utilisé par :
- cotisations (paiement Wave / Orange Money par un membre)
- prêts (remboursement Wave / Orange Money par un membre)
- prêts (décaissement Wave / Orange Money vers un membre)
"""

import logging

import httpx
from decouple import config


logger = logging.getLogger(__name__)


# ─── Configuration PayDunya ───────────────────────────────────────────────────

PAYDUNYA_MODE = config("PAYDUNYA_MODE", default="test")


# URLs de l'API PayDunya selon le mode
_BASE_URLS = {
    "test": "https://app.paydunya.com/sandbox-api/v1",
    "live": "https://app.paydunya.com/api/v1",
}


# En-têtes d'authentification PayDunya
_HEADERS = {
    "PAYDUNYA-MASTER-KEY": config("PAYDUNYA_MASTER_KEY", default=""),
    "PAYDUNYA-PRIVATE-KEY": config("PAYDUNYA_PRIVATE_KEY", default=""),
    "PAYDUNYA-PUBLIC-KEY": config("PAYDUNYA_PUBLIC_KEY", default=""),
    "PAYDUNYA-TOKEN": config("PAYDUNYA_TOKEN", default=""),
    "Content-Type": "application/json",
}


# URL de callback appelée par PayDunya après paiement
_CALLBACK_URL = config("PAYDUNYA_CALLBACK_URL", default="")


# Timeout pour les appels HTTP vers PayDunya
_TIMEOUT = 30


# ─── Exceptions métier ────────────────────────────────────────────────────────

class PayDunyaError(Exception):
    """Erreur retournée par l'API PayDunya."""
    pass


class PayDunyaNetworkError(Exception):
    """Erreur réseau ou timeout lors de la communication avec PayDunya."""
    pass


# ─── Pay-in : création d'une facture ─────────────────────────────────────────

def creer_facture(
    montant: int,
    description: str,
    reference: str,
    nom_client: str = "",
    email_client: str = "",
    telephone_client: str = "",
) -> dict:
    """
    Crée une facture PayDunya et retourne le token et l'URL de paiement.

    Retourne :

    {
        "token": "le_token_paydunya",
        "url_paiement": "https://app.paydunya.com/...",
        "response_code": "00",
    }
    """

    base_url = _BASE_URLS.get(
        PAYDUNYA_MODE,
        _BASE_URLS["test"]
    )

    endpoint = f"{base_url}/checkout-invoice/create"

    payload = {
        "invoice": {
            "total_amount": montant,
            "description": description,
        },
        "store": {
            "name": "SunuGestion",
        },
        "custom_data": {
            "reference": reference,
        },
        "actions": {
            "callback_url": _CALLBACK_URL,
        },
    }

    # Ajouter les informations du client si disponibles
    if nom_client or email_client or telephone_client:
        payload["customer"] = {}

        if nom_client:
            payload["customer"]["name"] = nom_client

        if email_client:
            payload["customer"]["email"] = email_client

        if telephone_client:
            payload["customer"]["phone"] = telephone_client

    logger.info(
        "PayDunya — création facture | mode=%s | montant=%s | ref=%s",
        PAYDUNYA_MODE,
        montant,
        reference,
    )

    try:
        response = httpx.post(
            endpoint,
            json=payload,
            headers=_HEADERS,
            timeout=_TIMEOUT,
        )

        response.raise_for_status()

    except httpx.TimeoutException as exc:
        logger.error(
            "PayDunya — timeout lors de la création de facture : %s",
            exc,
        )

        raise PayDunyaNetworkError(
            "Le service de paiement ne répond pas. Veuillez réessayer."
        ) from exc

    except httpx.NetworkError as exc:
        logger.error(
            "PayDunya — erreur réseau : %s",
            exc,
        )

        raise PayDunyaNetworkError(
            "Impossible de joindre le service de paiement."
        ) from exc

    except httpx.HTTPStatusError as exc:
        logger.error(
            "PayDunya — erreur HTTP %s : %s",
            exc.response.status_code,
            exc.response.text,
        )

        raise PayDunyaError(
            f"Le service de paiement a retourné une erreur "
            f"({exc.response.status_code})."
        ) from exc

    # Analyser la réponse JSON
    try:
        data = response.json()

    except Exception as exc:
        logger.error(
            "PayDunya — réponse non JSON : %s",
            response.text,
        )

        raise PayDunyaError(
            "Réponse inattendue du service de paiement."
        ) from exc

    # PayDunya retourne response_code="00" en cas de succès
    response_code = data.get("response_code", "")

    if response_code != "00":
        message_erreur = data.get(
            "response_text",
            "Erreur inconnue PayDunya.",
        )

        logger.error(
            "PayDunya — échec création facture | code=%s | message=%s",
            response_code,
            message_erreur,
        )

        raise PayDunyaError(message_erreur)

    token = data.get("token")

    if not token:
        logger.error(
            "PayDunya — token absent dans la réponse : %s",
            data,
        )

        raise PayDunyaError(
            "Token de paiement absent dans la réponse PayDunya."
        )

    # ─── Construction de l'URL de paiement ───────────────────────────────────
    #
    # Sandbox :
    # https://app.paydunya.com/sandbox-checkout/invoice/{token}
    #
    # Production :
    # https://app.paydunya.com/checkout/invoice/{token}

    if PAYDUNYA_MODE == "test":
        url_paiement = (
            f"https://app.paydunya.com/"
            f"sandbox-checkout/invoice/{token}"
        )
    else:
        url_paiement = (
            f"https://app.paydunya.com/"
            f"checkout/invoice/{token}"
        )

    logger.info(
        "PayDunya — facture créée | token=%s... | ref=%s",
        token[:8],
        reference,
    )

    return {
        "token": token,
        "url_paiement": url_paiement,
        "response_code": response_code,
    }


# ─── Pay-in : vérification d'une facture ─────────────────────────────────────

def verifier_facture(invoice_token: str) -> dict:
    """
    Vérifie le statut d'une facture PayDunya.

    Retourne :

    {
        "statut": "completed" | "pending" | "failed" | "cancelled",
        "montant_confirme": 5000,
        "response_code": "00",
        "response_text": "...",
    }
    """

    base_url = _BASE_URLS.get(
        PAYDUNYA_MODE,
        _BASE_URLS["test"]
    )

    endpoint = (
        f"{base_url}/checkout-invoice/confirm/"
        f"{invoice_token}"
    )

    logger.info(
        "PayDunya — vérification facture | mode=%s | token=%s...",
        PAYDUNYA_MODE,
        invoice_token[:8],
    )

    try:
        response = httpx.get(
            endpoint,
            headers=_HEADERS,
            timeout=_TIMEOUT,
        )

        response.raise_for_status()

    except httpx.TimeoutException as exc:
        logger.error(
            "PayDunya — timeout lors de la vérification : %s",
            exc,
        )

        raise PayDunyaNetworkError(
            "Le service de paiement ne répond pas. Veuillez réessayer."
        ) from exc

    except httpx.NetworkError as exc:
        logger.error(
            "PayDunya — erreur réseau lors de la vérification : %s",
            exc,
        )

        raise PayDunyaNetworkError(
            "Impossible de joindre le service de paiement."
        ) from exc

    except httpx.HTTPStatusError as exc:
        logger.error(
            "PayDunya — erreur HTTP %s lors de la vérification : %s",
            exc.response.status_code,
            exc.response.text,
        )

        raise PayDunyaError(
            f"Le service de paiement a retourné une erreur "
            f"({exc.response.status_code})."
        ) from exc

    try:
        data = response.json()

    except Exception as exc:
        logger.error(
            "PayDunya — réponse non JSON lors de la vérification : %s",
            response.text,
        )

        raise PayDunyaError(
            "Réponse inattendue du service de paiement."
        ) from exc

    response_code = data.get("response_code", "")
    response_text = data.get("response_text", "")

    # Le statut se trouve dans invoice.status
    invoice_data = data.get("invoice", {})

    statut_brut = invoice_data.get(
        "status",
        ""
    ).lower()

    # Normalisation du statut
    STATUTS_VALIDES = {
        "completed",
        "pending",
        "failed",
        "cancelled",
    }

    statut = (
        statut_brut
        if statut_brut in STATUTS_VALIDES
        else "failed"
    )

    # Montant confirmé par PayDunya
    try:
        montant_confirme = int(
            invoice_data.get("total_amount", 0)
        )

    except (TypeError, ValueError):
        montant_confirme = 0

    logger.info(
        "PayDunya — facture vérifiée | token=%s... | statut=%s | montant=%s",
        invoice_token[:8],
        statut,
        montant_confirme,
    )

    return {
        "statut": statut,
        "montant_confirme": montant_confirme,
        "response_code": response_code,
        "response_text": response_text,
    }


# ─── Pay-out : correspondance des modes ──────────────────────────────────────

_MODES_PAYOUT = {
    "wave": "wave-senegal",
    "orange_money": "orange-money-senegal",
}


# URL de base de l'API Pay-out PayDunya
_PAYOUT_BASE_URL = (
    "https://app.paydunya.com/api/v2/disburse"
)


# ─── Pay-out : initier un décaissement ───────────────────────────────────────

def initier_decaissement(
    montant: int,
    telephone_beneficiaire: str,
    mode_paiement: str,
    reference: str,
) -> dict:
    """
    Étape 1 du Pay-out PayDunya.

    Appelle :
    POST /api/v2/disburse/get-invoice
    """

    endpoint = f"{_PAYOUT_BASE_URL}/get-invoice"

    withdraw_mode = _MODES_PAYOUT.get(mode_paiement)

    if not withdraw_mode:
        raise PayDunyaError(
            "Mode de paiement non supporté pour le décaissement : "
            f"{mode_paiement}"
        )

    payload = {
        "account_alias": telephone_beneficiaire,
        "amount": montant,
        "withdraw_mode": withdraw_mode,
        "callback_url": _CALLBACK_URL,
        "custom_data": {
            "reference": reference,
        },
    }

    logger.info(
        "PayDunya Pay-out — initiation | mode=%s | montant=%s | ref=%s",
        mode_paiement,
        montant,
        reference,
    )

    return _appel_payout(
        endpoint,
        payload,
        "initiation décaissement",
    )


# ─── Pay-out : soumettre un décaissement ──────────────────────────────────────

def soumettre_decaissement(
    disburse_token: str,
    disburse_id: str,
) -> dict:
    """
    Étape 2 du Pay-out PayDunya.

    Appelle :
    POST /api/v2/disburse/submit-invoice
    """

    endpoint = f"{_PAYOUT_BASE_URL}/submit-invoice"

    payload = {
        "disburse_invoice": disburse_token,
        "disburse_id": disburse_id,
    }

    logger.info(
        "PayDunya Pay-out — soumission | token=%s... | id=%s",
        disburse_token[:8],
        disburse_id,
    )

    return _appel_payout(
        endpoint,
        payload,
        "soumission décaissement",
    )


# ─── Pay-out : vérifier un décaissement ───────────────────────────────────────

def verifier_decaissement(
    disburse_token: str,
) -> dict:
    """
    Vérifie le statut d'un décaissement PayDunya.

    Appelle :
    POST /api/v2/disburse/check-status

    Seul "success" permet de considérer le décaissement comme réussi.
    """

    endpoint = f"{_PAYOUT_BASE_URL}/check-status"

    payload = {
        "disburse_invoice": disburse_token,
    }

    logger.info(
        "PayDunya Pay-out — vérification statut | token=%s...",
        disburse_token[:8],
    )

    data = _appel_payout(
        endpoint,
        payload,
        "vérification décaissement",
    )

    statut_brut = data.get(
        "status",
        ""
    ).lower()

    STATUTS_VALIDES = {
        "created",
        "pending",
        "success",
        "failed",
    }

    statut = (
        statut_brut
        if statut_brut in STATUTS_VALIDES
        else "failed"
    )

    try:
        montant_confirme = int(
            data.get("amount", 0)
        )

    except (TypeError, ValueError):
        montant_confirme = 0

    logger.info(
        "PayDunya Pay-out — statut : %s | montant : %s | token : %s...",
        statut,
        montant_confirme,
        disburse_token[:8],
    )

    return {
        "statut": statut,
        "montant_confirme": montant_confirme,
        "response_code": data.get(
            "response_code",
            "",
        ),
        "response_text": data.get(
            "response_text",
            "",
        ),
    }


# ─── Helper Pay-out ───────────────────────────────────────────────────────────

def _appel_payout(
    endpoint: str,
    payload: dict,
    contexte: str,
) -> dict:
    """
    Effectue un appel POST vers l'API Pay-out PayDunya
    et retourne la réponse JSON parsée.
    """

    try:
        response = httpx.post(
            endpoint,
            json=payload,
            headers=_HEADERS,
            timeout=_TIMEOUT,
        )

        response.raise_for_status()

    except httpx.TimeoutException as exc:
        logger.error(
            "PayDunya Pay-out — timeout (%s) : %s",
            contexte,
            exc,
        )

        raise PayDunyaNetworkError(
            "Le service de paiement ne répond pas. Veuillez réessayer."
        ) from exc

    except httpx.NetworkError as exc:
        logger.error(
            "PayDunya Pay-out — erreur réseau (%s) : %s",
            contexte,
            exc,
        )

        raise PayDunyaNetworkError(
            "Impossible de joindre le service de paiement."
        ) from exc

    except httpx.HTTPStatusError as exc:
        logger.error(
            "PayDunya Pay-out — erreur HTTP %s (%s) : %s",
            exc.response.status_code,
            contexte,
            exc.response.text,
        )

        raise PayDunyaError(
            f"Le service de paiement a retourné une erreur "
            f"({exc.response.status_code})."
        ) from exc

    try:
        data = response.json()

    except Exception as exc:
        logger.error(
            "PayDunya Pay-out — réponse non JSON (%s) : %s",
            contexte,
            response.text,
        )

        raise PayDunyaError(
            "Réponse inattendue du service de paiement."
        ) from exc

    response_code = data.get(
        "response_code",
        "",
    )

    if response_code != "00":
        message_erreur = data.get(
            "response_text",
            "Erreur inconnue PayDunya.",
        )

        logger.error(
            "PayDunya Pay-out — échec (%s) | code=%s | message=%s",
            contexte,
            response_code,
            message_erreur,
        )

        raise PayDunyaError(message_erreur)

    return data