"""
Validateurs partagés pour tous les modules de SunuGestion.

Centralise les règles de validation métier communes afin d'éviter
la duplication entre authentication, membres, extraction, etc.
"""

import re

from django.contrib.auth import get_user_model

FORMAT_TELEPHONE = r'^(70|71|75|76|77|78)[0-9]{7}$'


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
