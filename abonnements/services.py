"""
Règles métier des abonnements SunuGestion.

- Essai gratuit de 30 jours à la création d'un groupement.
- Formule unique, mensuelle, dont le prix dépend des membres actifs.
- Tolérance de 2 membres au-dessus de chaque seuil (à la hausse).
- Pas de délai après l'essai ; 3 jours de grâce après une période payée.
"""

from datetime import timedelta

from dateutil.relativedelta import relativedelta
from django.db import transaction
from django.utils import timezone

from authentication.models import Utilisateur

from .models import Abonnement, PaiementAbonnement


DUREE_ESSAI_JOURS = 30
TOLERANCE_MEMBRES = 2

# (seuil maximum affiché, montant mensuel en FCFA) — None : sans limite
PALIERS = [
    (15, 2900),
    (34, 3900),
    (50, 4900),
    (None, 5900),
]


# ─── Tarif ────────────────────────────────────────────────────────────────────

def compter_membres_actifs(gie):
    """Membres actifs du groupement (ni en attente d'activation, ni suspendus)."""
    return Utilisateur.objects.filter(gie=gie, statut='actif').count()


def calculer_tarif(nombre_membres):
    """
    Montant mensuel pour un nombre de membres actifs, tolérance comprise.

    Retourne le montant, le palier appliqué et les informations utiles
    pour prévenir le groupement avant un changement de palier.
    """
    for index, (seuil, montant) in enumerate(PALIERS):
        if seuil is None or nombre_membres <= seuil + TOLERANCE_MEMBRES:
            suivant = PALIERS[index + 1] if index + 1 < len(PALIERS) else None
            return {
                'montant': montant,
                'palier': index + 1,
                'seuil': seuil,
                # Au-delà du seuil affiché mais sans changer de palier
                'dans_tolerance': seuil is not None and nombre_membres > seuil,
                'membres_avant_palier_suivant': (
                    seuil + TOLERANCE_MEMBRES + 1 - nombre_membres
                    if suivant else None
                ),
                'montant_palier_suivant': suivant[1] if suivant else None,
            }

    raise ValueError("Grille tarifaire invalide.")  # pragma: no cover


def grille_tarifaire():
    """Grille affichable : paliers, montants et tolérance."""
    lignes = []
    minimum = 1
    for seuil, montant in PALIERS:
        lignes.append({'membres_min': minimum, 'membres_max': seuil, 'montant': montant})
        if seuil is not None:
            minimum = seuil + 1
    return {'paliers': lignes, 'tolerance': TOLERANCE_MEMBRES}


# ─── Abonnement d'un groupement ───────────────────────────────────────────────

def obtenir_abonnement(gie):
    """
    Abonnement du groupement. Un groupement qui n'en a pas encore reçoit
    un essai gratuit de 30 jours à partir d'aujourd'hui.
    """
    aujourd_hui = timezone.localdate()

    abonnement, _ = Abonnement.objects.get_or_create(
        gie=gie,
        defaults={
            'statut': 'essai',
            'date_debut': aujourd_hui,
            'date_fin': aujourd_hui + timedelta(days=DUREE_ESSAI_JOURS - 1),
        }
    )
    return abonnement


def acces_ecriture_autorise(gie):
    """Faux si le groupement est en lecture seule (abonnement expiré)."""
    return obtenir_abonnement(gie).acces_ecriture()


def periode_suivante(abonnement, aujourd_hui=None):
    """
    Période couverte par un nouveau paiement.

    - Payé avant la lecture seule (essai, période en cours ou délai de grâce) :
      la nouvelle période suit immédiatement la précédente. Les jours d'essai
      restants ne sont pas perdus, le délai de grâce n'est pas offert.
    - Payé en lecture seule : la nouvelle période commence le jour du paiement.
    """
    aujourd_hui = aujourd_hui or timezone.localdate()

    if aujourd_hui < abonnement.date_lecture_seule():
        debut = abonnement.date_fin + timedelta(days=1)
    else:
        debut = aujourd_hui

    fin = debut + relativedelta(months=1) - timedelta(days=1)
    return debut, fin


def creer_paiement(gie, mode_paiement, initie_par=None, note=''):
    """Paiement en attente, au tarif calculé maintenant sur les membres actifs."""
    abonnement = obtenir_abonnement(gie)
    nombre = compter_membres_actifs(gie)

    return PaiementAbonnement.objects.create(
        abonnement=abonnement,
        montant=calculer_tarif(nombre)['montant'],
        nombre_membres=nombre,
        mode_paiement=mode_paiement,
        initie_par=initie_par,
        note=note,
    )


def valider_paiement(paiement):
    """
    Valide un paiement et prolonge l'abonnement d'un mois.
    Idempotent : un paiement déjà validé n'est jamais compté deux fois.
    Retourne True si le paiement vient d'être validé.
    """
    with transaction.atomic():
        paiement = PaiementAbonnement.objects.select_for_update().get(pk=paiement.pk)
        if paiement.statut == 'valide':
            return False

        abonnement = Abonnement.objects.select_for_update().get(pk=paiement.abonnement_id)
        debut, fin = periode_suivante(abonnement)

        abonnement.statut = 'actif'
        abonnement.date_debut = debut
        abonnement.date_fin = fin
        abonnement.save(update_fields=['statut', 'date_debut', 'date_fin', 'date_mise_a_jour'])

        paiement.statut = 'valide'
        paiement.periode_debut = debut
        paiement.periode_fin = fin
        paiement.date_validation = timezone.now()
        paiement.save(update_fields=['statut', 'periode_debut', 'periode_fin', 'date_validation'])

    return True


def marquer_paiement_echoue(paiement):
    PaiementAbonnement.objects.filter(
        pk=paiement.pk, statut='en_attente'
    ).update(statut='echoue')
