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

# URLs des pages de paiement (checkout) : domaine paydunya.com, SANS "app."
_CHECKOUT_URLS = {
    "test": "https://paydunya.com/sandbox-checkout/invoice",
    "live": "https://paydunya.com/checkout/invoice",
}

# En-têtes d'authentification PayDunya
_HEADERS = {
    "PAYDUNYA-MASTER-KEY": config("PAYDUNYA_MASTER_KEY", default=""),
    "PAYDUNYA-PRIVATE-KEY": config("PAYDUNYA_PRIVATE_KEY", default=""),
    "PAYDUNYA-PUBLIC-KEY": config("PAYDUNYA_PUBLIC_KEY", default=""),
    "PAYDUNYA-TOKEN": config("PAYDUNYA_TOKEN", default=""),
    "Content-Type": "application/json",
}

# URL de callback appelée par PayDunya après paiement (HTTPS publique)
_CALLBACK_URL = config("PAYDUNYA_CALLBACK_URL", default="")
_RETURN_URL = config("PAYDUNYA_RETURN_URL", default="")
_CANCEL_URL = config("PAYDUNYA_CANCEL_URL", default="")

# Timeout pour les appels HTTP vers PayDunya
_TIMEOUT = 30


def _base_url() -> str:
    return _BASE_URLS.get(PAYDUNYA_MODE, _BASE_URLS["test"])


def _checkout_url() -> str:
    return _CHECKOUT_URLS.get(PAYDUNYA_MODE, _CHECKOUT_URLS["test"])


# ─── Exceptions métier ────────────────────────────────────────────────────────

class PayDunyaError(Exception):
    """Erreur retournée par l'API PayDunya."""
    pass


class PayDunyaNetworkError(Exception):
    """Erreur réseau ou timeout lors de la communication avec PayDunya."""
    pass


# ─── Helper HTTP commun ───────────────────────────────────────────────────────

def _requete(
    methode: str,
    endpoint: str,
    contexte: str,
    payload: dict | None = None,
) -> dict:
    """
    Effectue un appel HTTP vers PayDunya, gère les erreurs réseau/HTTP/JSON
    et vérifie que response_code == "00". Retourne le JSON parsé.
    """

    try:
        if methode == "POST":
            response = httpx.post(
                endpoint,
                json=payload,
                headers=_HEADERS,
                timeout=_TIMEOUT,
            )
        else:
            response = httpx.get(
                endpoint,
                headers=_HEADERS,
                timeout=_TIMEOUT,
            )

        response.raise_for_status()

    except httpx.TimeoutException as exc:
        logger.error("PayDunya — timeout (%s) : %s", contexte, exc)
        raise PayDunyaNetworkError(
            "Le service de paiement ne répond pas. Veuillez réessayer."
        ) from exc

    except httpx.NetworkError as exc:
        logger.error("PayDunya — erreur réseau (%s) : %s", contexte, exc)
        raise PayDunyaNetworkError(
            "Impossible de joindre le service de paiement."
        ) from exc

    except httpx.HTTPStatusError as exc:
        logger.error(
            "PayDunya — erreur HTTP %s (%s) : %s",
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
            "PayDunya — réponse non JSON (%s) : %s",
            contexte,
            response.text,
        )
        raise PayDunyaError(
            "Réponse inattendue du service de paiement."
        ) from exc

    response_code = data.get("response_code", "")

    if response_code != "00":
        message_erreur = data.get("response_text", "Erreur inconnue PayDunya.")
        logger.error(
            "PayDunya — échec (%s) | code=%s | message=%s",
            contexte,
            response_code,
            message_erreur,
        )
        raise PayDunyaError(message_erreur)

    return data


# ─── Pay-in : création d'une facture ─────────────────────────────────────────

def creer_facture(
    montant: int,
    description: str,
    reference: str,
    nom_client: str = "",
    email_client: str = "",
    telephone_client: str = "",
    return_url: str  = "",
    cancel_url: str ="",
) -> dict:
    """
    Crée une facture PayDunya et retourne le token et l'URL de paiement.

    Retourne :
    {
        "token": "le_token_paydunya",
        "url_paiement": "https://paydunya.com/...",
        "response_code": "00",
    }
    """

    endpoint = f"{_base_url()}/checkout-invoice/create"

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
            "return_url": return_url or _RETURN_URL,
            "cancel_url": cancel_url or _CANCEL_URL,
        },
    }

    # Informations du client si disponibles
    customer = {}
    if nom_client:
        customer["name"] = nom_client
    if email_client:
        customer["email"] = email_client
    if telephone_client:
        customer["phone"] = telephone_client
    if customer:
        payload["customer"] = customer

    logger.info(
        "PayDunya — création facture | mode=%s | montant=%s | ref=%s",
        PAYDUNYA_MODE,
        montant,
        reference,
    )

    data = _requete("POST", endpoint, "création facture", payload)

    token = data.get("token")

    if not token:
        logger.error("PayDunya — token absent dans la réponse : %s", data)
        raise PayDunyaError("Token de paiement absent dans la réponse PayDunya.")

    # ─── URL de paiement ─────────────────────────────────────────────────────
    # PayDunya renvoie l'URL de checkout dans response_text.
    # Fallback : on la reconstruit sur paydunya.com (sans "app.").
    url_paiement = data.get("response_text", "")

    if not str(url_paiement).startswith("http"):
        url_paiement = f"{_checkout_url()}/{token}"

    logger.info(
        "PayDunya — facture créée | token=%s... | ref=%s | url=%s",
        token[:8],
        reference,
        url_paiement,
    )

    return {
        "token": token,
        "url_paiement": url_paiement,
        "response_code": data.get("response_code", ""),
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

    endpoint = f"{_base_url()}/checkout-invoice/confirm/{invoice_token}"

    logger.info(
        "PayDunya — vérification facture | mode=%s | token=%s...",
        PAYDUNYA_MODE,
        invoice_token[:8],
    )

    data = _requete("GET", endpoint, "vérification facture")

    invoice_data = data.get("invoice", {}) or {}

    # CORRECTION : le statut est au premier niveau de la réponse
    # (data["status"]), avec repli sur invoice.status.
    statut_brut = str(
        data.get("status") or invoice_data.get("status") or ""
    ).lower()

    statuts_valides = {"completed", "pending", "failed", "cancelled"}
    statut = statut_brut if statut_brut in statuts_valides else "failed"

    # Montant confirmé par PayDunya
    try:
        montant_confirme = int(float(invoice_data.get("total_amount", 0)))
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
        "response_code": data.get("response_code", ""),
        "response_text": data.get("response_text", ""),
    }


# ─── Pay-out : configuration ─────────────────────────────────────────────────

_MODES_PAYOUT = {
    "wave": "wave-senegal",
    "orange_money": "orange-money-senegal",
}

# ATTENTION : l'API Pay-out n'a pas de sandbox dédié. Même avec
# PAYDUNYA_MODE=test, ces appels visent l'API réelle : vérifie la
# documentation PayDunya avant de tester des décaissements.
_PAYOUT_BASE_URL = "https://app.paydunya.com/api/v2/disburse"


# ─── Pay-out : initier un décaissement ───────────────────────────────────────

def initier_decaissement(
    montant: int,
    telephone_beneficiaire: str,
    mode_paiement: str,
    reference: str,
) -> dict:
    """
    Étape 1 du Pay-out PayDunya.
    Appelle : POST /api/v2/disburse/get-invoice
    """

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

    return _requete(
        "POST",
        f"{_PAYOUT_BASE_URL}/get-invoice",
        "initiation décaissement",
        payload,
    )


# ─── Pay-out : soumettre un décaissement ──────────────────────────────────────

def soumettre_decaissement(
    disburse_token: str,
    disburse_id: str,
) -> dict:
    """
    Étape 2 du Pay-out PayDunya.
    Appelle : POST /api/v2/disburse/submit-invoice
    """

    payload = {
        "disburse_invoice": disburse_token,
        "disburse_id": disburse_id,
    }

    logger.info(
        "PayDunya Pay-out — soumission | token=%s... | id=%s",
        disburse_token[:8],
        disburse_id,
    )

    return _requete(
        "POST",
        f"{_PAYOUT_BASE_URL}/submit-invoice",
        "soumission décaissement",
        payload,
    )


# ─── Pay-out : vérifier un décaissement ───────────────────────────────────────

def verifier_decaissement(disburse_token: str) -> dict:
    """
    Vérifie le statut d'un décaissement PayDunya.
    Appelle : POST /api/v2/disburse/check-status

    Seul "success" permet de considérer le décaissement comme réussi.
    """

    payload = {"disburse_invoice": disburse_token}

    logger.info(
        "PayDunya Pay-out — vérification statut | token=%s...",
        disburse_token[:8],
    )

    data = _requete(
        "POST",
        f"{_PAYOUT_BASE_URL}/check-status",
        "vérification décaissement",
        payload,
    )

    statut_brut = str(data.get("status", "")).lower()

    statuts_valides = {"created", "pending", "success", "failed"}
    statut = statut_brut if statut_brut in statuts_valides else "failed"

    try:
        montant_confirme = int(float(data.get("amount", 0)))
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
        "response_code": data.get("response_code", ""),
        "response_text": data.get("response_text", ""),
    }

from urllib.parse import urlencode

def construire_url_retour(type_paiement: str, objet_id: int) -> str:
    sep = "&" if "?" in _RETURN_URL else "?"
    return f"{_RETURN_URL}{sep}{urlencode({'type': type_paiement, 'id': objet_id})}"