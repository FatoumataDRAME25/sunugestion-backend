import calendar
from datetime import datetime, time, timedelta
from decimal import Decimal
from io import BytesIO
from xml.sax.saxutils import escape

from django.db.models import Count, Q, Sum
from django.utils import timezone

from activites.models import Activite
from cotisations.models import Cotisation
from historiques.models import HistoriqueOperation
from prets.models import Pret
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)


TYPES_PERIODE = ('mensuel', 'trimestriel', 'annuel')

ANNEE_MIN = 2000
ANNEE_MAX = 9998

NOMS_MOIS = [
    'Janvier', 'Février', 'Mars', 'Avril', 'Mai', 'Juin',
    'Juillet', 'Août', 'Septembre', 'Octobre', 'Novembre', 'Décembre',
]

NOMS_TRIMESTRES = {
    1: '1er trimestre',
    2: '2e trimestre',
    3: '3e trimestre',
    4: '4e trimestre',
}

NON_DISPONIBLE = 'Non disponible'


# ─── Période ──────────────────────────────────────────────────────────────────

def obtenir_periode(type_periode, annee, mois=None, trimestre=None):
    """
    Retourne les dates de début et de fin inclusives
    de la période demandée.
    """

    if (
        isinstance(annee, bool)
        or not isinstance(annee, int)
        or not ANNEE_MIN <= annee <= ANNEE_MAX
    ):
        raise ValueError(
            f"L'année doit être comprise entre {ANNEE_MIN} et {ANNEE_MAX}."
        )

    if type_periode == 'mensuel':
        if mois is None or not 1 <= mois <= 12:
            raise ValueError("Le mois doit être compris entre 1 et 12.")

        debut = datetime(annee, mois, 1).date()

        if mois == 12:
            fin = datetime(annee + 1, 1, 1).date() - timedelta(days=1)
        else:
            fin = datetime(annee, mois + 1, 1).date() - timedelta(days=1)

    elif type_periode == 'trimestriel':
        if trimestre is None or not 1 <= trimestre <= 4:
            raise ValueError("Le trimestre doit être compris entre 1 et 4.")

        premier_mois = (trimestre - 1) * 3 + 1
        debut = datetime(annee, premier_mois, 1).date()

        if trimestre == 4:
            fin = datetime(annee + 1, 1, 1).date() - timedelta(days=1)
        else:
            fin = datetime(annee, premier_mois + 3, 1).date() - timedelta(days=1)

    elif type_periode == 'annuel':
        debut = datetime(annee, 1, 1).date()
        fin = datetime(annee, 12, 31).date()

    else:
        raise ValueError(
            "La période doit être mensuelle, trimestrielle ou annuelle."
        )

    return debut, fin


MOIS_PAR_TYPE_PERIODE = {
    'mensuel': 1,
    'trimestriel': 3,
    'annuel': 12,
}

def _reculer_de_mois(jour, nombre_mois):
    """
    Même quantième, `nombre_mois` plus tôt. Si ce jour n'existe pas dans le
    mois d'arrivée (ex : 31 mars - 1 mois), on retient le dernier jour du mois.
    """
    index = jour.year * 12 + (jour.month - 1) - nombre_mois
    annee, mois = divmod(index, 12)
    mois += 1
    dernier_jour = calendar.monthrange(annee, mois)[1]

    return jour.replace(year=annee, month=mois, day=min(jour.day, dernier_jour))


def obtenir_periode_rapport(
    type_periode, annee, mois=None, trimestre=None, aujourd_hui=None
):
    """
    Retourne (début, fin, glissante) pour le rapport, dates inclusives.

    - Période passée : période calendaire complète.
    - Période en cours (elle contient aujourd'hui) : période glissante qui se
      termine aujourd'hui et remonte d'un mois, d'un trimestre ou d'un an.
      Exemple : octobre demandé le 13 octobre → du 13 septembre au 13 octobre.
    """

    debut, fin = obtenir_periode(type_periode, annee, mois, trimestre)

    if aujourd_hui is None:
        aujourd_hui = timezone.localdate()

    if debut <= aujourd_hui <= fin:
        debut = _reculer_de_mois(
            aujourd_hui, MOIS_PAR_TYPE_PERIODE[type_periode]
        )
        return debut, aujourd_hui, True

    return debut, fin, False


def obtenir_libelle_periode(type_periode, annee, mois=None, trimestre=None):
    """Retourne le libellé lisible de la période (ex : « Mars 2026 »)."""

    if type_periode == 'mensuel':
        return f"{NOMS_MOIS[mois - 1]} {annee}"

    if type_periode == 'trimestriel':
        return f"{NOMS_TRIMESTRES[trimestre]} {annee}"

    return f"Année {annee}"


def obtenir_nom_fichier(type_periode, annee, mois=None, trimestre=None):
    """Retourne le nom du fichier PDF correspondant à la période."""

    if type_periode == 'mensuel':
        suffixe = f"{annee}-{mois:02d}"
    elif type_periode == 'trimestriel':
        suffixe = f"{annee}-T{trimestre}"
    else:
        suffixe = f"{annee}"

    return f"rapport-gestion-{suffixe}.pdf"


def _debut_de_journee(jour):
    """Minuit (fuseau du projet) du jour fourni, sous forme de datetime aware."""
    return timezone.make_aware(
        datetime.combine(jour, time.min),
        timezone.get_current_timezone()
    )


def _bornes_periode(debut, fin):
    """
    Convertit les dates inclusives en bornes datetime [début, fin exclusive[
    afin d'inclure toute la dernière journée sans erreur de fuseau horaire.
    """
    return _debut_de_journee(debut), _debut_de_journee(fin + timedelta(days=1))


# ─── Bilan financier ──────────────────────────────────────────────────────────

def calculer_bilan_financier(gie, debut, fin):
    """
    Calcule le bilan de trésorerie du groupement pour une période.
    Les dates de début et de fin sont inclusives.
    """

    borne_debut, borne_fin = _bornes_periode(debut, fin)

    operations = HistoriqueOperation.objects.filter(
        gie=gie
    )

    # Solde avant le début de la période
    operations_anterieures = operations.filter(
        date_operation__lt=borne_debut
    )

    entrees_anterieures = operations_anterieures.filter(
        type_operation='entree'
    ).aggregate(total=Sum('montant'))['total'] or Decimal('0')

    sorties_anterieures = operations_anterieures.filter(
        type_operation='sortie'
    ).aggregate(total=Sum('montant'))['total'] or Decimal('0')

    solde_initial = entrees_anterieures - sorties_anterieures

    # Opérations réalisées pendant la période
    operations_periode = operations.filter(
        date_operation__gte=borne_debut,
        date_operation__lt=borne_fin
    )

    entrees = operations_periode.filter(
        type_operation='entree'
    ).aggregate(total=Sum('montant'))['total'] or Decimal('0')

    sorties = operations_periode.filter(
        type_operation='sortie'
    ).aggregate(total=Sum('montant'))['total'] or Decimal('0')

    solde_final = solde_initial + entrees - sorties

    return {
        'solde_initial': solde_initial,
        'total_entrees': entrees,
        'total_sorties': sorties,
        'solde_final': solde_final,
    }


# ─── Cotisations ──────────────────────────────────────────────────────────────

def calculer_statistiques_cotisations(gie, debut, fin):
    """
    Paiements de cotisations réellement encaissés pendant la période.

    Les montants proviennent uniquement des opérations de trésorerie liées
    à une cotisation : chaque paiement n'est donc compté qu'une seule fois.
    """

    borne_debut, borne_fin = _bornes_periode(debut, fin)

    paiements = HistoriqueOperation.objects.filter(
        gie=gie,
        type_operation='entree',
        cotisation__isnull=False,
        date_operation__gte=borne_debut,
        date_operation__lt=borne_fin
    ).aggregate(
        nombre=Count('id'),
        total=Sum('montant')
    )

    # Retards : situation arrêtée à la fin de la période, ou à aujourd'hui
    # si la période n'est pas encore terminée. Une cotisation est en retard
    # lorsque sa session est échue et qu'elle n'était pas réglée à cette date.
    date_situation = min(fin, timezone.localdate())
    lendemain = _debut_de_journee(date_situation + timedelta(days=1))

    retards = Cotisation.objects.filter(
        membre__gie=gie,
        session__date_fin__lt=date_situation
    ).filter(
        ~Q(statut='paye') |
        Q(statut='paye', date_paiement__gte=lendemain)
    ).aggregate(
        nombre=Count('id'),
        total=Sum('session__montant')
    )

    return {
        'nombre_paiements': paiements['nombre'],
        'montant_collecte': paiements['total'] or Decimal('0'),
        'date_situation_retards': date_situation,
        'nombre_en_retard': retards['nombre'],
        'montant_en_retard': retards['total'] or Decimal('0'),
    }


# ─── Prêts ────────────────────────────────────────────────────────────────────

def calculer_statistiques_prets(gie, debut, fin):
    """
    Prêts accordés, décaissés et remboursés pendant la période, d'après les
    dates d'approbation et les opérations de trésorerie réellement enregistrées.

    Les prêts « en cours » et « en retard » reflètent la situation au moment
    de la génération : ce ne sont pas des statuts historiques.
    """

    borne_debut, borne_fin = _bornes_periode(debut, fin)

    prets = Pret.objects.filter(membre__gie=gie)

    accordes = prets.filter(
        date_approbation__gte=borne_debut,
        date_approbation__lt=borne_fin
    ).aggregate(
        nombre=Count('id'),
        total=Sum('montant')
    )

    operations_prets = HistoriqueOperation.objects.filter(
        gie=gie,
        pret__isnull=False,
        date_operation__gte=borne_debut,
        date_operation__lt=borne_fin
    )

    decaissements = operations_prets.filter(
        type_operation='sortie'
    ).aggregate(
        nombre=Count('id'),
        total=Sum('montant')
    )

    remboursements = operations_prets.filter(
        type_operation='entree'
    ).aggregate(
        nombre=Count('id'),
        total=Sum('montant')
    )

    # Situation actuelle (mêmes règles que le diagnostic financier)
    aujourd_hui = timezone.localdate()

    nombre_en_retard = prets.filter(
        Q(statut='en_retard') |
        Q(statut='en_cours', date_echeance__lt=aujourd_hui)
    ).count()

    nombre_en_cours = prets.filter(
        statut='en_cours'
    ).exclude(
        date_echeance__lt=aujourd_hui
    ).count()

    return {
        'nombre_accordes': accordes['nombre'],
        'montant_accorde': accordes['total'] or Decimal('0'),
        'nombre_decaissements': decaissements['nombre'],
        'montant_decaisse': decaissements['total'] or Decimal('0'),
        'nombre_remboursements': remboursements['nombre'],
        'montant_rembourse': remboursements['total'] or Decimal('0'),
        'date_situation': aujourd_hui,
        'nombre_en_cours': nombre_en_cours,
        'nombre_en_retard': nombre_en_retard,
    }


# ─── Activités et participation ───────────────────────────────────────────────

def calculer_taux_presence(presences, absences):
    """
    Taux de présence en pourcentage, ou None si rien n'est enregistré.
    Une présence non enregistrée n'est jamais comptée comme une absence.
    """
    total = presences + absences

    if total == 0:
        return None

    return (
        Decimal(presences) * Decimal('100') / Decimal(total)
    ).quantize(Decimal('0.1'))


def _activites_periode(gie, debut, fin):
    borne_debut, borne_fin = _bornes_periode(debut, fin)

    return Activite.objects.filter(
        gie=gie,
        date_activite__gte=borne_debut,
        date_activite__lt=borne_fin
    )


def calculer_statistiques_activites(gie, debut, fin):
    """
    Nombre d'activités de la période par statut.
    Il s'agit du statut actuel de chaque activité.
    """

    activites = _activites_periode(gie, debut, fin)

    par_statut = {
        'planifiee': 0,
        'en_cours': 0,
        'terminee': 0,
        'annulee': 0,
    }

    for ligne in activites.order_by().values('statut').annotate(
        nombre=Count('id')
    ):
        par_statut[ligne['statut']] = (
            par_statut.get(ligne['statut'], 0) + ligne['nombre']
        )

    return {
        'total': sum(par_statut.values()),
        'planifiees': par_statut['planifiee'],
        'en_cours': par_statut['en_cours'],
        'terminees': par_statut['terminee'],
        'annulees': par_statut['annulee'],
    }


def lister_activites_par_statut(gie, debut, fin):
    """
    Détail des activités de la période, regroupées selon leur statut actuel.
    Aucune donnée nominative : seuls des nombres de présences et d'absences
    réellement enregistrées sont retournés.
    """

    activites = _activites_periode(gie, debut, fin).annotate(
        nombre_presents=Count(
            'presences', filter=Q(presences__statut='present')
        ),
        nombre_absents=Count(
            'presences', filter=Q(presences__statut='absent')
        )
    ).order_by('date_activite', 'id')

    par_statut = {
        'planifiee': [],
        'en_cours': [],
        'terminee': [],
        'annulee': [],
    }

    for activite in activites:
        par_statut.setdefault(activite.statut, []).append({
            'titre': activite.titre,
            'date_planification': timezone.localtime(
                activite.date_creation
            ).date(),
            'date_prevue': timezone.localtime(activite.date_activite),
            'presences': activite.nombre_presents,
            'absences': activite.nombre_absents,
            'taux_presence': calculer_taux_presence(
                activite.nombre_presents,
                activite.nombre_absents
            ),
        })

    return par_statut


def calculer_statistiques_participation(gie, debut, fin):
    """
    Statistiques agrégées de présence, sans aucune donnée nominative.
    Seules les présences et absences réellement enregistrées sont comptées.
    """

    activites = _activites_periode(gie, debut, fin).annotate(
        nombre_presents=Count(
            'presences', filter=Q(presences__statut='present')
        ),
        nombre_absents=Count(
            'presences', filter=Q(presences__statut='absent')
        )
    ).order_by('date_activite', 'id')

    par_activite = []
    presences = 0
    absences = 0
    activites_sans_enregistrement = 0

    for activite in activites:
        if activite.nombre_presents + activite.nombre_absents == 0:
            activites_sans_enregistrement += 1
            continue

        presences += activite.nombre_presents
        absences += activite.nombre_absents

        par_activite.append({
            'titre': activite.titre,
            'date': timezone.localtime(activite.date_activite).date(),
            'presences': activite.nombre_presents,
            'absences': activite.nombre_absents,
            'taux_presence': calculer_taux_presence(
                activite.nombre_presents,
                activite.nombre_absents
            ),
        })

    return {
        'presences': presences,
        'absences': absences,
        'taux_presence': calculer_taux_presence(presences, absences),
        'activites_sans_enregistrement': activites_sans_enregistrement,
        'par_activite': par_activite,
    }


# ─── Mise en forme ────────────────────────────────────────────────────────────

def formater_montant(montant):
    """Formate un montant en FCFA avec séparateur de milliers."""
    return f"{int(montant):,}".replace(',', ' ') + ' FCFA'


def formater_taux(taux):
    """Formate un taux en pourcentage, ou « Non disponible »."""
    if taux is None:
        return NON_DISPONIBLE

    return f"{taux}".replace('.', ',') + ' %'


def _formater_date(jour):
    return jour.strftime('%d/%m/%Y')


# ─── Synthèse ─────────────────────────────────────────────────────────────────

def construire_synthese(donnees):
    """
    Synthèse factuelle et déterministe : chaque phrase reprend uniquement
    des chiffres calculés, sans interprétation ni intelligence artificielle.
    """

    bilan = donnees['bilan']
    cotisations = donnees['cotisations']
    prets = donnees['prets']
    activites = donnees['activites']
    participation = donnees['participation']

    variation = bilan['solde_final'] - bilan['solde_initial']
    signe = '+' if variation > 0 else ''

    phrases = [
        (
            f"Le solde de trésorerie est passé de "
            f"{formater_montant(bilan['solde_initial'])} en début de période à "
            f"{formater_montant(bilan['solde_final'])} en fin de période, "
            f"soit une variation de {signe}{formater_montant(variation)}."
        ),
        (
            f"Les entrées de la période s'élèvent à "
            f"{formater_montant(bilan['total_entrees'])} et les sorties à "
            f"{formater_montant(bilan['total_sorties'])}."
        ),
        (
            f"{cotisations['nombre_paiements']} paiement(s) de cotisation "
            f"ont été enregistrés, pour un montant collecté de "
            f"{formater_montant(cotisations['montant_collecte'])}."
        ),
        (
            f"{prets['nombre_accordes']} prêt(s) ont été accordés pour un "
            f"montant de {formater_montant(prets['montant_accorde'])}, et "
            f"{formater_montant(prets['montant_rembourse'])} de remboursements "
            f"ont été enregistrés."
        ),
        (
            f"{activites['total']} activité(s) sont datées de la période, "
            f"dont {activites['terminees']} terminée(s) et "
            f"{activites['annulees']} annulée(s)."
        ),
    ]

    if participation['taux_presence'] is None:
        phrases.append(
            "Aucune présence ni absence n'a été enregistrée pour les "
            "activités de la période : le taux de présence n'est pas "
            "disponible."
        )
    else:
        phrases.append(
            f"{participation['presences']} présence(s) et "
            f"{participation['absences']} absence(s) ont été enregistrées, "
            f"soit un taux de présence de "
            f"{formater_taux(participation['taux_presence'])}."
        )

    return phrases


# ─── Collecte des données ─────────────────────────────────────────────────────

def collecter_donnees_rapport(gie, type_periode, annee, mois=None, trimestre=None):
    """
    Réunit toutes les données du rapport périodique du groupement fourni.
    Aucun appel à une IA n'est effectué ici.
    """

    date_generation = timezone.localtime()
    debut, fin, glissante = obtenir_periode_rapport(
        type_periode, annee, mois, trimestre,
        aujourd_hui=date_generation.date()
    )

    # Une période glissante n'a pas de libellé : seules ses dates sont affichées
    if glissante:
        libelle = None
    else:
        libelle = obtenir_libelle_periode(type_periode, annee, mois, trimestre)

    donnees = {
        'gie': {
            'nom': gie.nom,
            'type': gie.get_type_gie_display() if gie.type_gie else None,
        },
        'periode': {
            'type': type_periode,
            'libelle': libelle,
            'debut': debut,
            'fin': fin,
            'glissante': glissante,
        },
        'date_generation': date_generation,
        'bilan': calculer_bilan_financier(gie, debut, fin),
        'cotisations': calculer_statistiques_cotisations(gie, debut, fin),
        'prets': calculer_statistiques_prets(gie, debut, fin),
        'activites': calculer_statistiques_activites(gie, debut, fin),
        'activites_detail': lister_activites_par_statut(gie, debut, fin),
        'participation': calculer_statistiques_participation(gie, debut, fin),
    }

    donnees['synthese'] = construire_synthese(donnees)

    return donnees


# ─── Génération du PDF ────────────────────────────────────────────────────────

COULEUR_PRINCIPALE = colors.HexColor('#1E3A5F')
COULEUR_FOND_CLAIR = colors.HexColor('#F7F8FA')
COULEUR_BORDURE = colors.HexColor('#D9DEE5')
COULEUR_TEXTE_SECONDAIRE = colors.HexColor('#4A5568')

LARGEUR_UTILE = A4[0] - 4 * cm


def _styles_pdf():
    base = getSampleStyleSheet()

    return {
        'titre': ParagraphStyle(
            'TitreRapport',
            parent=base['Title'],
            fontName='Helvetica-Bold',
            fontSize=15,
            leading=20,
            alignment=TA_CENTER,
            textColor=COULEUR_PRINCIPALE,
            spaceAfter=4,
        ),
        'sous_titre': ParagraphStyle(
            'SousTitreRapport',
            parent=base['Normal'],
            fontSize=11,
            leading=14,
            alignment=TA_CENTER,
            textColor=COULEUR_TEXTE_SECONDAIRE,
        ),
        'section': ParagraphStyle(
            'SectionRapport',
            parent=base['Heading2'],
            fontName='Helvetica-Bold',
            fontSize=12,
            leading=16,
            textColor=COULEUR_PRINCIPALE,
            spaceBefore=14,
            spaceAfter=6,
            keepWithNext=True,
        ),
        'sous_section': ParagraphStyle(
            'SousSectionRapport',
            parent=base['Heading3'],
            fontName='Helvetica-Bold',
            fontSize=10,
            leading=13,
            textColor=COULEUR_PRINCIPALE,
            spaceBefore=10,
            spaceAfter=4,
            keepWithNext=True,
        ),
        'texte': ParagraphStyle(
            'TexteRapport',
            parent=base['Normal'],
            fontSize=10,
            leading=14,
        ),
        'note': ParagraphStyle(
            'NoteRapport',
            parent=base['Normal'],
            fontName='Helvetica-Oblique',
            fontSize=8.5,
            leading=11,
            textColor=COULEUR_TEXTE_SECONDAIRE,
            spaceBefore=4,
        ),
        'cellule': ParagraphStyle(
            'CelluleRapport',
            parent=base['Normal'],
            fontSize=9.5,
            leading=12,
        ),
    }


def _tableau_indicateurs(lignes, styles):
    """Tableau à deux colonnes : libellé de l'indicateur et valeur."""

    donnees = [
        [Paragraph(escape(libelle), styles['cellule']), valeur]
        for libelle, valeur in lignes
    ]

    tableau = Table(
        donnees,
        colWidths=[LARGEUR_UTILE * 0.62, LARGEUR_UTILE * 0.38]
    )

    tableau.setStyle(TableStyle([
        ('FONTNAME', (1, 0), (1, -1), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 9.5),
        ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('ROWBACKGROUNDS', (0, 0), (-1, -1), [colors.white, COULEUR_FOND_CLAIR]),
        ('GRID', (0, 0), (-1, -1), 0.5, COULEUR_BORDURE),
        ('TOPPADDING', (0, 0), (-1, -1), 5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
        ('LEFTPADDING', (0, 0), (-1, -1), 8),
        ('RIGHTPADDING', (0, 0), (-1, -1), 8),
    ]))

    return tableau


TITRES_STATUTS_ACTIVITES = [
    ('planifiee', 'Activités planifiées'),
    ('en_cours', 'Activités en cours'),
    ('terminee', 'Activités terminées'),
    ('annulee', 'Activités annulées'),
]


def _tableau_activites(activites, styles, avec_presences=False):
    """
    Tableau détaillé des activités d'un statut. L'en-tête est répété
    lorsque le tableau se poursuit sur une autre page.
    """

    entetes = ['Date de planification', "Titre de l'activité", 'Date prévue']
    largeurs = [0.24, 0.52, 0.24]

    if avec_presences:
        entetes += ['Présences', 'Absences', 'Taux de présence']
        largeurs = [0.15, 0.31, 0.15, 0.12, 0.11, 0.16]

    style_entete = ParagraphStyle(
        'EnteteActivites',
        parent=styles['cellule'],
        fontName='Helvetica-Bold',
        fontSize=8.5,
        leading=10.5,
        alignment=TA_CENTER,
        textColor=colors.white,
    )

    donnees = [[Paragraph(entete, style_entete) for entete in entetes]]

    for activite in activites:
        ligne = [
            _formater_date(activite['date_planification']),
            Paragraph(escape(activite['titre']), styles['cellule']),
            _formater_date(activite['date_prevue']),
        ]

        if avec_presences:
            ligne += [
                str(activite['presences']),
                str(activite['absences']),
                formater_taux(activite['taux_presence']),
            ]

        donnees.append(ligne)

    tableau = Table(
        donnees,
        colWidths=[LARGEUR_UTILE * largeur for largeur in largeurs],
        repeatRows=1
    )

    tableau.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), COULEUR_PRINCIPALE),
        ('FONTSIZE', (0, 1), (-1, -1), 9),
        ('ALIGN', (0, 1), (0, -1), 'CENTER'),
        ('ALIGN', (2, 1), (-1, -1), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, COULEUR_FOND_CLAIR]),
        ('GRID', (0, 0), (-1, -1), 0.5, COULEUR_BORDURE),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
    ]))

    return tableau


def _pied_de_page(canvas, document):
    canvas.saveState()
    canvas.setFont('Helvetica', 8)
    canvas.setFillColor(COULEUR_TEXTE_SECONDAIRE)
    canvas.drawString(2 * cm, 1.2 * cm, 'SunuGestion - Rapport périodique de gestion')
    canvas.drawRightString(A4[0] - 2 * cm, 1.2 * cm, f'Page {document.page}')
    canvas.restoreState()


def generer_rapport_pdf(donnees):
    """
    Génère en mémoire le PDF du rapport à partir des données calculées
    par collecter_donnees_rapport et retourne son contenu binaire.
    """

    styles = _styles_pdf()

    gie = donnees['gie']
    periode = donnees['periode']
    bilan = donnees['bilan']
    cotisations = donnees['cotisations']
    prets = donnees['prets']
    activites = donnees['activites']
    activites_detail = donnees['activites_detail']

    tampon = BytesIO()

    document = SimpleDocTemplate(
        tampon,
        pagesize=A4,
        leftMargin=2 * cm,
        rightMargin=2 * cm,
        topMargin=2 * cm,
        bottomMargin=2 * cm,
        title='Rapport périodique de gestion du groupement',
        author='SunuGestion',
    )

    elements = [
        Paragraph('RAPPORT PÉRIODIQUE DE GESTION DU GROUPEMENT', styles['titre']),
        Paragraph(escape(gie['nom']), styles['sous_titre']),
        Spacer(1, 0.4 * cm),
    ]

    # A. Informations générales
    elements.append(Paragraph('Informations générales', styles['section']))

    informations = [('Nom du groupement', Paragraph(escape(gie['nom']), styles['cellule']))]

    if gie['type']:
        informations.append(('Type de groupement', gie['type']))

    dates_periode = (
        f"{_formater_date(periode['debut'])} "
        f"au {_formater_date(periode['fin'])}"
    )

    if periode['libelle']:
        texte_periode = f"{escape(periode['libelle'])}<br/>du {dates_periode}"
    else:
        texte_periode = f"Du {dates_periode}"

    informations += [
        ('Période', Paragraph(texte_periode, styles['cellule'])),
        (
            'Document généré le',
            donnees['date_generation'].strftime('%d/%m/%Y à %H:%M')
        ),
    ]

    elements.append(_tableau_indicateurs(informations, styles))

    # B. Bilan financier
    elements.append(Paragraph('Bilan financier', styles['section']))
    elements.append(_tableau_indicateurs([
        ('Solde initial de trésorerie', formater_montant(bilan['solde_initial'])),
        ('Total des entrées de la période', formater_montant(bilan['total_entrees'])),
        ('Total des sorties de la période', formater_montant(bilan['total_sorties'])),
        ('Solde final de trésorerie', formater_montant(bilan['solde_final'])),
    ], styles))
    elements.append(Paragraph(
        'Solde final = solde initial + entrées de la période - sorties de la période.',
        styles['note']
    ))

    # C. Cotisations
    elements.append(Paragraph('Cotisations', styles['section']))
    date_retards = _formater_date(cotisations['date_situation_retards'])
    elements.append(_tableau_indicateurs([
        ('Paiements enregistrés pendant la période', str(cotisations['nombre_paiements'])),
        ('Montant collecté pendant la période', formater_montant(cotisations['montant_collecte'])),
        (f'Cotisations échues non réglées au {date_retards}', str(cotisations['nombre_en_retard'])),
        (f'Montant restant dû sur ces cotisations au {date_retards}', formater_montant(cotisations['montant_en_retard'])),
    ], styles))
    elements.append(Paragraph(
        "Le montant collecté correspond aux paiements réellement encaissés, "
        "et non au montant théorique attendu.",
        styles['note']
    ))

    # D. Prêts
    elements.append(Paragraph('Prêts', styles['section']))
    date_prets = _formater_date(prets['date_situation'])
    elements.append(_tableau_indicateurs([
        ('Prêts accordés pendant la période', str(prets['nombre_accordes'])),
        ('Montant des prêts accordés', formater_montant(prets['montant_accorde'])),
        ('Décaissements enregistrés pendant la période', str(prets['nombre_decaissements'])),
        ('Montant décaissé', formater_montant(prets['montant_decaisse'])),
        ('Remboursements enregistrés pendant la période', str(prets['nombre_remboursements'])),
        ('Montant remboursé', formater_montant(prets['montant_rembourse'])),
        (f'Prêts en cours au {date_prets}', str(prets['nombre_en_cours'])),
        (f'Prêts en retard au {date_prets}', str(prets['nombre_en_retard'])),
    ], styles))
    elements.append(Paragraph(
        f"Les prêts en cours et en retard correspondent à la situation au "
        f"{date_prets}, date de génération du rapport, et non à la situation "
        f"en fin de période.",
        styles['note']
    ))

    # E. Activités
    elements.append(Paragraph(
        f"Activités de la période ({activites['total']})",
        styles['section']
    ))
    elements.append(Paragraph(
        "Activités dont la date prévue appartient à la période, classées "
        "selon leur statut au moment de la génération du rapport.",
        styles['note']
    ))

    for statut, titre in TITRES_STATUTS_ACTIVITES:
        activites_statut = activites_detail[statut]

        elements.append(Paragraph(
            f"{titre} ({len(activites_statut)})",
            styles['sous_section']
        ))

        if not activites_statut:
            elements.append(Paragraph(
                'Aucune activité pour cette période.',
                styles['note']
            ))
            continue

        elements.append(_tableau_activites(
            activites_statut,
            styles,
            avec_presences=(statut == 'terminee')
        ))

    # F. Synthèse
    elements.append(Paragraph('Synthèse', styles['section']))
    for phrase in donnees['synthese']:
        elements.append(Paragraph(f"- {escape(phrase)}", styles['texte']))
        elements.append(Spacer(1, 0.1 * cm))

    document.build(
        elements,
        onFirstPage=_pied_de_page,
        onLaterPages=_pied_de_page
    )

    return tampon.getvalue()
