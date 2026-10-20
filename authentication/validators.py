"""
Validateurs partagés pour tous les modules de SunuGestion.

Centralise les règles de validation métier communes afin d'éviter
la duplication entre authentication, membres, extraction, etc.
"""

import re

from django.contrib.auth import get_user_model
from rest_framework import serializers

FORMAT_TELEPHONE = r'^(70|71|75|76|77|78)[0-9]{7}$'

# Le groupement peut avoir un numéro fixe (33…) en plus des mobiles
FORMAT_TELEPHONE_GIE = r'^(33|70|71|75|76|77|78)[0-9]{7}$'


def valider_nom_gie(nom):
    """Nom du groupement : non vide et sans balises HTML. Retourne le nom nettoyé."""
    nom = nom.strip()
    if not nom:
        raise serializers.ValidationError("Le nom du groupement ne peut pas être vide.")
    if '<' in nom or '>' in nom:
        raise serializers.ValidationError(
            "Le nom du groupement ne doit pas contenir les caractères < ou >."
        )
    return nom


def valider_telephone_gie(telephone):
    """
    Téléphone du groupement (facultatif) : 9 chiffres, mobile ou fixe.
    Les espaces sont ignorés. Retourne le numéro nettoyé.
    """
    if not telephone:
        return telephone
    telephone = re.sub(r'\s', '', telephone)
    if not re.match(FORMAT_TELEPHONE_GIE, telephone):
        raise serializers.ValidationError(
            "Numéro invalide : 9 chiffres commençant par 33, 70, 71, 75, 76, 77 ou 78."
        )
    return telephone


def valider_telephone(telephone, exclure_id=None):
    """
    Valide le format sénégalais et l'unicité du numéro de téléphone.

    Paramètres :
    - telephone   : numéro à valider (string)
    - exclure_id  : ID de l'utilisateur à exclure de la vérification
                    d'unicité (utile lors d'une modification de profil)

    Retourne (telephone_nettoye, liste_erreurs).
    Si liste_erreurs est vide, le numéro est valide.
    """
    Utilisateur = get_user_model()
    erreurs = []
    telephone = str(telephone).strip()

    if not re.match(FORMAT_TELEPHONE, telephone):
        erreurs.append(
            "Format invalide — doit commencer par 70, 71, 75, 76, 77 ou 78 "
            "et contenir 9 chiffres au total."
        )

    qs = Utilisateur.objects.filter(telephone=telephone)
    if exclure_id:
        qs = qs.exclude(id=exclure_id)

    if qs.exists():
        erreurs.append("Ce numéro de téléphone est déjà utilisé.")

    return telephone, erreurs
