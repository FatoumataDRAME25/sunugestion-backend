import re

import httpx
from asgiref.sync import async_to_sync
from django.http import HttpRequest, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from rest_framework import serializers

from membres.serializers import (
    valider_nom_prenom,
    valider_telephone,
    valider_role,
)

from .config import settings
from .n8n_client import send_text_to_n8n
from .ocr_service import extract_text_from_image
from .schemas import OCRResult, Person, ProcessDocumentResponse

ALLOWED_CONTENT_TYPES = {"image/jpeg", "image/png", "image/jpg", "image/webp"}

# Taille max autorisée : 5 Mo
MAX_FILE_SIZE_MB = 5
MAX_FILE_SIZE_BYTES = MAX_FILE_SIZE_MB * 1024 * 1024


def _validate_image(uploaded_file) -> None:
    """Valide le type MIME et la taille du fichier image."""
    if uploaded_file.content_type not in ALLOWED_CONTENT_TYPES:
        raise ValueError(
            f"Format non supporté : {uploaded_file.content_type}. "
            f"Formats acceptés : JPEG, PNG, WEBP."
        )
    if uploaded_file.size > MAX_FILE_SIZE_BYTES:
        raise ValueError(
            f"Fichier trop volumineux : {uploaded_file.size // (1024*1024)} Mo. "
            f"Maximum autorisé : {MAX_FILE_SIZE_MB} Mo."
        )


def _valider_personne(person: dict) -> tuple[dict, list[str]]:
    """
    Applique les mêmes validations que AjoutMembreSerializer
    (membres/serializers.py) sur les données extraites par l'OCR.
    Retourne (données_validées, liste_erreurs).
    """
    erreurs = []
    donnees = {}

    # --- Prénom ---
    prenom = str(person.get("prenom") or "").strip()
    if not prenom:
        erreurs.append("Prénom manquant")
    else:
        try:
            donnees["prenom"] = valider_nom_prenom(prenom, "prénom")
        except serializers.ValidationError as exc:
            erreurs.extend(
                exc.detail if isinstance(exc.detail, list) else [str(exc.detail)]
            )

    # --- Nom ---
    nom = str(person.get("nom") or "").strip()
    if not nom:
        erreurs.append("Nom manquant")
    else:
        try:
            donnees["nom"] = valider_nom_prenom(nom, "nom")
        except serializers.ValidationError as exc:
            erreurs.extend(
                exc.detail if isinstance(exc.detail, list) else [str(exc.detail)]
            )

    # --- Téléphone ---
    telephone = str(person.get("telephone") or "").strip()
    if not telephone:
        erreurs.append("Téléphone manquant")
    else:
        telephone_valide, erreurs_tel = valider_telephone(telephone)
        donnees["telephone"] = telephone_valide
        erreurs.extend(erreurs_tel)

    # --- Rôle ---
    role = str(person.get("role") or "").strip().lower()
    if not role:
        erreurs.append("Rôle manquant")
    else:
        role_valide, erreurs_role = valider_role(role)
        donnees["role"] = role_valide
        erreurs.extend(erreurs_role)

    # Champs optionnels — pas de validation stricte, on les passe tels quels
    for champ in ("email", "date_naissance", "numero_piece", "adresse"):
        valeur = person.get(champ)
        if valeur:
            donnees[champ] = str(valeur).strip()

    return donnees, erreurs


def _table_person_fields(raw_text: str) -> list[dict[str, str]]:
    lines = [line.strip() for line in raw_text.splitlines() if line.strip()]
    normalized = [re.sub(r"[^a-z]", "", line.lower()) for line in lines]
    headers = ["prenom", "nom", "telephone", "email", "role"]

    for start in range(len(lines) - len(headers) + 1):
        if normalized[start : start + len(headers)] != headers:
            continue

        values = lines[start + len(headers) :]
        fields: list[dict[str, str]] = []
        for offset in range(0, len(values) - len(headers) + 1, len(headers)):
            row = values[offset : offset + len(headers)]
            if len(row) < len(headers):
                break
            if any(
                normalized_value in headers
                for normalized_value in [
                    re.sub(r"[^a-z]", "", value.lower()) for value in row
                ]
            ):
                continue
            fields.append(dict(zip(headers, row)))
        return fields

    return []


def _error_response(message: str, status: int) -> JsonResponse:
    return JsonResponse({"detail": message}, status=status)


def health(request: HttpRequest) -> JsonResponse:
    return JsonResponse({"status": "ok"})


@csrf_exempt
def ocr_only(request: HttpRequest) -> JsonResponse:
    """
    POST /api/ocr
    Body : multipart/form-data  { file: <image> }
    Retourne le texte brut extrait, sans validation des données.
    """
    if request.method != "POST":
        return _error_response("Méthode non autorisée", 405)

    uploaded_file = request.FILES.get("file")
    if uploaded_file is None:
        return _error_response("Champ 'file' requis", 400)
    try:
        _validate_image(uploaded_file)
    except ValueError as exc:
        return _error_response(str(exc), 400)

    result = extract_text_from_image(
        uploaded_file.read(), lang=settings.paddleocr_lang
    )
    return JsonResponse(OCRResult(**result).model_dump())


@csrf_exempt
def process_document(request: HttpRequest) -> JsonResponse:
    """
    POST /api/process-document
    Body : multipart/form-data  { file: <image> }

    Retourne :
    {
      "rawText": "...",
      "persons": [
        {
          "prenom": "...", "nom": "...", "telephone": "...",
          "role": "...", "email": "...",   // champs optionnels
          "erreurs": ["..."]               // présent seulement si invalide
        }
      ],
      "count": 3,
      "validCount": 2,
      "invalidCount": 1
    }
    """
    if request.method != "POST":
        return _error_response("Méthode non autorisée", 405)

    uploaded_file = request.FILES.get("file")
    if uploaded_file is None:
        return _error_response("Champ 'file' requis", 400)
    try:
        _validate_image(uploaded_file)
    except ValueError as exc:
        return _error_response(str(exc), 400)

    ocr_result = extract_text_from_image(
        uploaded_file.read(), lang=settings.paddleocr_lang
    )
    raw_text = ocr_result["raw_text"]
    if not raw_text.strip():
        return _error_response("Aucun texte détecté sur l'image", 422)

    try:
        n8n_result = async_to_sync(send_text_to_n8n)(
            raw_text, image_filename=uploaded_file.name
        )
    except httpx.HTTPStatusError as exc:
        return _error_response(f"n8n a répondu une erreur : {exc}", 502)
    except Exception as exc:
        return _error_response(f"Impossible de contacter n8n : {exc}", 502)

    persons_raw = n8n_result.get("persons", [])

    # Enrichissement depuis le tableau détecté dans le texte brut
    table_fields = _table_person_fields(raw_text)
    for idx, person in enumerate(persons_raw):
        if idx < len(table_fields):
            for key, value in table_fields[idx].items():
                if not person.get(key):
                    person[key] = (
                        re.sub(r"(?:amail|qmail)", "gmail", value, flags=re.IGNORECASE)
                        if key == "email"
                        else value
                    )

    # Validation avec les règles de membres/serializers.py
    persons_valides = []
    persons_invalides = []

    for person in persons_raw:
        donnees_validees, erreurs = _valider_personne(person)
        if erreurs:
            # On renvoie les données brutes + les erreurs pour correction côté Angular
            persons_invalides.append({**person, "erreurs": erreurs})
        else:
            persons_valides.append(donnees_validees)

    response_data = {
        "rawText": raw_text,
        "persons": persons_valides + persons_invalides,
        "count": len(persons_raw),
        "validCount": len(persons_valides),
        "invalidCount": len(persons_invalides),
    }

    return JsonResponse(response_data)
