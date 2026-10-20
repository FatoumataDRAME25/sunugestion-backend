from django.db.models import Sum, Q
from django.utils import timezone

from cotisations.models import Cotisation
from prets.models import Pret
from historiques.views import calculer_solde


def calculer_indicateurs(gie):
    """
    Calcule les indicateurs financiers du groupement fourni.
    Aucun appel à une IA n'est effectué ici.
    """

    aujourd_hui = timezone.now().date()

    # 1. INDICATEURS DES COTISATIONS
    cotisations = Cotisation.objects.filter(membre__gie=gie)

    cotisations_en_retard = cotisations.filter(
        Q(statut='en_retard') |
        Q(
            statut='en_cours',
            session__date_fin__lt=aujourd_hui
        )
    )

    cotisations_en_cours = cotisations.filter(
        statut='en_cours'
    ).exclude(
        session__date_fin__lt=aujourd_hui
    )

    cotisations_payees = cotisations.filter(statut='paye')

    montant_cotisations_payees = cotisations_payees.aggregate(
        total=Sum('session__montant')
    )['total'] or 0


    montant_cotisations_en_retard = cotisations_en_retard.aggregate(
        total=Sum('session__montant')
    )['total'] or 0

    # 2. INDICATEURS DES PRÊTS
    prets = Pret.objects.filter(membre__gie=gie)

    prets_en_retard = prets.filter(
        Q(statut='en_retard') |
        Q(
            statut='en_cours',
            date_echeance__lt=aujourd_hui
        )
    )

    prets_en_cours = prets.filter(
        statut='en_cours'
    ).exclude(
        date_echeance__lt=aujourd_hui
    )

    prets_rembourses = prets.filter(statut='rembourse')

    montant_prets_en_cours = prets_en_cours.aggregate(
        total=Sum('montant')
    )['total'] or 0

    montant_prets_en_retard = prets_en_retard.aggregate(
        total=Sum('montant')
    )['total'] or 0

    montant_prets_rembourses = prets_rembourses.aggregate(
        total=Sum('montant')
    )['total'] or 0

    # 3. INDICATEURS DE TRÉSORERIE
    total_entrees, total_sorties, solde = calculer_solde(gie)

    # 4. RÉSULTAT
    return {
        'date_analyse': aujourd_hui.isoformat(),

        'cotisations': {
            'nombre_payees': cotisations_payees.count(),
            'nombre_en_cours': cotisations_en_cours.count(),
            'nombre_en_retard': cotisations_en_retard.count(),
            'montant_paye': float(montant_cotisations_payees),
            'montant_en_retard': float(montant_cotisations_en_retard),
        },

        'prets': {
            'nombre_en_cours': prets_en_cours.count(),
            'nombre_en_retard': prets_en_retard.count(),
            'nombre_rembourses': prets_rembourses.count(),
            'montant_en_cours': float(montant_prets_en_cours),
            'montant_en_retard': float(montant_prets_en_retard),
            'montant_rembourse': float(montant_prets_rembourses),
        },

        'tresorerie': {
            'total_entrees': float(total_entrees),
            'total_sorties': float(total_sorties),
            'solde': float(solde),
        },
    }