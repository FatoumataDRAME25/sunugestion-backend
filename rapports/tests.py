from datetime import date, datetime, timedelta
from decimal import Decimal

import pymupdf
from django.test import SimpleTestCase, TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from activites.models import Activite, Presence
from authentication.models import GIE, Utilisateur
from cotisations.models import Cotisation, SessionCotisation
from historiques.models import HistoriqueOperation
from prets.models import Pret
from rapports.services import (
    calculer_bilan_financier,
    calculer_statistiques_activites,
    calculer_statistiques_cotisations,
    calculer_statistiques_participation,
    calculer_statistiques_prets,
    collecter_donnees_rapport,
    generer_rapport_pdf,
    lister_activites_par_statut,
    obtenir_nom_fichier,
    obtenir_periode,
    obtenir_periode_rapport,
)


URL_RAPPORT = '/api/rapports/periodique/'


def moment(annee, mois, jour, heure=12, minute=0, seconde=0):
    """Datetime aware dans le fuseau du projet."""
    return timezone.make_aware(
        datetime(annee, mois, jour, heure, minute, seconde)
    )


def creer_gie(nom, code):
    return GIE.objects.create(
        nom=nom,
        region='Dakar',
        type_gie='groupement',
        code=code,
        statut='actif'
    )


def creer_utilisateur(gie, telephone, role, nom='Diop', prenom='Awa'):
    # Sans mot de passe : aucun hachage, les tests restent rapides.
    return Utilisateur.objects.create_user(
        telephone=telephone,
        nom=nom,
        prenom=prenom,
        role=role,
        gie=gie,
        statut='actif'
    )


def creer_operation(gie, type_operation, montant, quand, **liens):
    operation = HistoriqueOperation.objects.create(
        gie=gie,
        type_operation=type_operation,
        montant=montant,
        libelle='Opération de test',
        **liens
    )
    # date_operation est en auto_now_add : on la fixe après création.
    HistoriqueOperation.objects.filter(pk=operation.pk).update(
        date_operation=quand
    )
    return operation


def texte_pdf(contenu):
    with pymupdf.open(stream=contenu, filetype='pdf') as document:
        texte = ''.join(page.get_text() for page in document)
    return ' '.join(texte.replace(' ', ' ').split())


# ─── A. Périodes ──────────────────────────────────────────────────────────────

class PeriodeTestCase(SimpleTestCase):

    def test_mois_normal(self):
        self.assertEqual(
            obtenir_periode('mensuel', 2024, mois=4),
            (date(2024, 4, 1), date(2024, 4, 30))
        )

    def test_fevrier_bissextile(self):
        self.assertEqual(
            obtenir_periode('mensuel', 2024, mois=2),
            (date(2024, 2, 1), date(2024, 2, 29))
        )

    def test_decembre(self):
        self.assertEqual(
            obtenir_periode('mensuel', 2024, mois=12),
            (date(2024, 12, 1), date(2024, 12, 31))
        )

    def test_chaque_trimestre(self):
        attendus = {
            1: (date(2024, 1, 1), date(2024, 3, 31)),
            2: (date(2024, 4, 1), date(2024, 6, 30)),
            3: (date(2024, 7, 1), date(2024, 9, 30)),
            4: (date(2024, 10, 1), date(2024, 12, 31)),
        }

        for trimestre, attendu in attendus.items():
            with self.subTest(trimestre=trimestre):
                self.assertEqual(
                    obtenir_periode('trimestriel', 2024, trimestre=trimestre),
                    attendu
                )

    def test_annee_entiere(self):
        self.assertEqual(
            obtenir_periode('annuel', 2024),
            (date(2024, 1, 1), date(2024, 12, 31))
        )

    def test_parametres_invalides(self):
        cas = [
            ('mensuel', 2024, {'mois': 0}),
            ('mensuel', 2024, {'mois': 13}),
            ('mensuel', 2024, {}),
            ('trimestriel', 2024, {'trimestre': 0}),
            ('trimestriel', 2024, {'trimestre': 5}),
            ('trimestriel', 2024, {}),
            ('hebdomadaire', 2024, {}),
            ('annuel', 1999, {}),
            ('annuel', 10000, {}),
            ('annuel', '2024', {}),
            ('annuel', None, {}),
        ]

        for type_periode, annee, options in cas:
            with self.subTest(type_periode=type_periode, annee=annee, **options):
                with self.assertRaises(ValueError):
                    obtenir_periode(type_periode, annee, **options)

    def test_periode_en_cours_glissante(self):
        aujourd_hui = date(2026, 10, 13)

        self.assertEqual(
            obtenir_periode_rapport('mensuel', 2026, mois=10, aujourd_hui=aujourd_hui),
            (date(2026, 9, 13), date(2026, 10, 13), True)
        )
        self.assertEqual(
            obtenir_periode_rapport('trimestriel', 2026, trimestre=4, aujourd_hui=aujourd_hui),
            (date(2026, 7, 13), date(2026, 10, 13), True)
        )
        self.assertEqual(
            obtenir_periode_rapport('annuel', 2026, aujourd_hui=aujourd_hui),
            (date(2025, 10, 13), date(2026, 10, 13), True)
        )

    def test_periode_passee_reste_calendaire(self):
        aujourd_hui = date(2026, 10, 13)

        self.assertEqual(
            obtenir_periode_rapport('mensuel', 2026, mois=9, aujourd_hui=aujourd_hui),
            (date(2026, 9, 1), date(2026, 9, 30), False)
        )
        self.assertEqual(
            obtenir_periode_rapport('trimestriel', 2026, trimestre=3, aujourd_hui=aujourd_hui),
            (date(2026, 7, 1), date(2026, 9, 30), False)
        )
        self.assertEqual(
            obtenir_periode_rapport('annuel', 2025, aujourd_hui=aujourd_hui),
            (date(2025, 1, 1), date(2025, 12, 31), False)
        )

    def test_periode_glissante_aux_limites(self):
        # Premier et dernier jour de la période calendaire
        self.assertEqual(
            obtenir_periode_rapport('mensuel', 2026, mois=10, aujourd_hui=date(2026, 10, 1)),
            (date(2026, 9, 1), date(2026, 10, 1), True)
        )
        self.assertEqual(
            obtenir_periode_rapport('mensuel', 2026, mois=10, aujourd_hui=date(2026, 10, 31)),
            (date(2026, 9, 30), date(2026, 10, 31), True)
        )
        # Le quantième n'existe pas dans le mois d'arrivée
        self.assertEqual(
            obtenir_periode_rapport('mensuel', 2026, mois=3, aujourd_hui=date(2026, 3, 31)),
            (date(2026, 2, 28), date(2026, 3, 31), True)
        )
        self.assertEqual(
            obtenir_periode_rapport('annuel', 2024, aujourd_hui=date(2024, 2, 29)),
            (date(2023, 2, 28), date(2024, 2, 29), True)
        )
        # Janvier : la période glissante commence l'année précédente
        self.assertEqual(
            obtenir_periode_rapport('trimestriel', 2026, trimestre=1, aujourd_hui=date(2026, 1, 10)),
            (date(2025, 10, 10), date(2026, 1, 10), True)
        )

    def test_nom_fichier(self):
        self.assertEqual(
            obtenir_nom_fichier('mensuel', 2024, mois=3),
            'rapport-gestion-2024-03.pdf'
        )
        self.assertEqual(
            obtenir_nom_fichier('trimestriel', 2024, trimestre=2),
            'rapport-gestion-2024-T2.pdf'
        )
        self.assertEqual(
            obtenir_nom_fichier('annuel', 2024),
            'rapport-gestion-2024.pdf'
        )


# ─── Données communes ─────────────────────────────────────────────────────────

class DonneesRapportMixin:

    @classmethod
    def setUpTestData(cls):
        cls.gie = creer_gie('Groupement Alpha', 'ALPHA')
        cls.autre_gie = creer_gie('Groupement Beta', 'BETA')

        cls.president = creer_utilisateur(cls.gie, '770000001', 'president')
        cls.tresorier = creer_utilisateur(cls.gie, '770000002', 'tresorier')
        cls.secretaire = creer_utilisateur(cls.gie, '770000003', 'secretaire')
        cls.membre = creer_utilisateur(
            cls.gie, '770000004', 'membre',
            nom='Ndiayetest', prenom='Khadijatest'
        )
        cls.president_beta = creer_utilisateur(
            cls.autre_gie, '770000005', 'president'
        )
        cls.membre_beta = creer_utilisateur(
            cls.autre_gie, '770000006', 'membre'
        )


# ─── B. Calculs financiers ────────────────────────────────────────────────────

class BilanFinancierTestCase(DonneesRapportMixin, TestCase):

    def test_solde_initial_entrees_sorties_et_solde_final(self):
        # Avant la période
        creer_operation(self.gie, 'entree', 100000, moment(2024, 1, 10))
        creer_operation(self.gie, 'sortie', 30000, moment(2024, 2, 20))
        # Pendant la période (mars 2024)
        creer_operation(self.gie, 'entree', 50000, moment(2024, 3, 5))
        creer_operation(self.gie, 'sortie', 20000, moment(2024, 3, 15))
        # Après la période
        creer_operation(self.gie, 'entree', 999, moment(2024, 4, 2))
        # Autre groupement : ne doit jamais être compté
        creer_operation(self.autre_gie, 'entree', 777777, moment(2024, 3, 10))

        bilan = calculer_bilan_financier(
            self.gie, date(2024, 3, 1), date(2024, 3, 31)
        )

        self.assertEqual(bilan['solde_initial'], Decimal('70000'))
        self.assertEqual(bilan['total_entrees'], Decimal('50000'))
        self.assertEqual(bilan['total_sorties'], Decimal('20000'))
        self.assertEqual(bilan['solde_final'], Decimal('100000'))
        self.assertEqual(
            bilan['solde_final'],
            bilan['solde_initial']
            + bilan['total_entrees']
            - bilan['total_sorties']
        )

    def test_periode_sans_operation(self):
        creer_operation(self.gie, 'entree', 40000, moment(2024, 1, 10))

        bilan = calculer_bilan_financier(
            self.gie, date(2024, 3, 1), date(2024, 3, 31)
        )

        self.assertEqual(bilan['solde_initial'], Decimal('40000'))
        self.assertEqual(bilan['total_entrees'], Decimal('0'))
        self.assertEqual(bilan['total_sorties'], Decimal('0'))
        self.assertEqual(bilan['solde_final'], Decimal('40000'))

    def test_aucune_operation_du_tout(self):
        bilan = calculer_bilan_financier(
            self.gie, date(2024, 3, 1), date(2024, 3, 31)
        )

        self.assertEqual(bilan['solde_initial'], Decimal('0'))
        self.assertEqual(bilan['solde_final'], Decimal('0'))

    def test_limites_exactes_entre_deux_periodes(self):
        # Dernière seconde de février, première et dernière seconde de mars,
        # première seconde d'avril.
        creer_operation(self.gie, 'entree', 1, moment(2024, 2, 29, 23, 59, 59))
        creer_operation(self.gie, 'entree', 10, moment(2024, 3, 1, 0, 0, 0))
        creer_operation(self.gie, 'entree', 100, moment(2024, 3, 31, 23, 59, 59))
        creer_operation(self.gie, 'entree', 1000, moment(2024, 4, 1, 0, 0, 0))

        mars = calculer_bilan_financier(
            self.gie, date(2024, 3, 1), date(2024, 3, 31)
        )
        avril = calculer_bilan_financier(
            self.gie, date(2024, 4, 1), date(2024, 4, 30)
        )

        self.assertEqual(mars['solde_initial'], Decimal('1'))
        self.assertEqual(mars['total_entrees'], Decimal('110'))
        self.assertEqual(mars['solde_final'], Decimal('111'))

        # Le solde final d'une période est le solde initial de la suivante.
        self.assertEqual(avril['solde_initial'], mars['solde_final'])
        self.assertEqual(avril['total_entrees'], Decimal('1000'))


# ─── C. Données métier ────────────────────────────────────────────────────────

class CotisationsTestCase(DonneesRapportMixin, TestCase):

    def creer_session(self, date_debut, date_fin, montant=5000):
        return SessionCotisation.objects.create(
            createur=self.tresorier, gie=self.tresorier.gie,
            libelle='Session de test',
            montant=montant,
            date_debut=date_debut,
            date_fin=date_fin
        )

    def payer(self, cotisation, quand):
        cotisation.statut = 'paye'
        cotisation.date_paiement = quand
        cotisation.mode_paiement = 'especes'
        cotisation.save()
        creer_operation(
            self.gie, 'entree', cotisation.session.montant, quand,
            cotisation=cotisation
        )

    def test_cotisations_sans_double_comptage(self):
        session = self.creer_session(date(2024, 3, 1), date(2024, 3, 31))
        cotisation = Cotisation.objects.create(
            session=session, membre=self.membre
        )
        # Cotisation non payée : montant attendu mais pas encaissé
        Cotisation.objects.create(session=session, membre=self.secretaire)

        self.payer(cotisation, moment(2024, 3, 10))
        # Entrée manuelle sans lien avec une cotisation
        creer_operation(self.gie, 'entree', 2000, moment(2024, 3, 12))

        stats = calculer_statistiques_cotisations(
            self.gie, date(2024, 3, 1), date(2024, 3, 31)
        )
        bilan = calculer_bilan_financier(
            self.gie, date(2024, 3, 1), date(2024, 3, 31)
        )

        self.assertEqual(stats['nombre_paiements'], 1)
        self.assertEqual(stats['montant_collecte'], Decimal('5000'))
        # Le paiement figure une seule fois dans les entrées de trésorerie.
        self.assertEqual(bilan['total_entrees'], Decimal('7000'))

    def test_paiement_hors_periode_non_compte(self):
        session = self.creer_session(date(2024, 3, 1), date(2024, 4, 30))
        cotisation = Cotisation.objects.create(
            session=session, membre=self.membre
        )
        self.payer(cotisation, moment(2024, 4, 3))

        mars = calculer_statistiques_cotisations(
            self.gie, date(2024, 3, 1), date(2024, 3, 31)
        )
        avril = calculer_statistiques_cotisations(
            self.gie, date(2024, 4, 1), date(2024, 4, 30)
        )

        self.assertEqual(mars['nombre_paiements'], 0)
        self.assertEqual(mars['montant_collecte'], Decimal('0'))
        self.assertEqual(avril['nombre_paiements'], 1)

    def test_retards_a_la_fin_de_la_periode(self):
        session = self.creer_session(date(2024, 2, 1), date(2024, 2, 15))
        payee_tard = Cotisation.objects.create(
            session=session, membre=self.membre
        )
        Cotisation.objects.create(
            session=session, membre=self.secretaire, statut='en_retard'
        )
        # Réglée en avril : en retard fin mars, plus en retard fin avril.
        self.payer(payee_tard, moment(2024, 4, 5))

        # Session non échue fin mars : pas un retard.
        session_ouverte = self.creer_session(date(2024, 3, 1), date(2024, 5, 31))
        Cotisation.objects.create(session=session_ouverte, membre=self.membre)

        # Autre groupement
        session_beta = SessionCotisation.objects.create(
            createur=self.president_beta, gie=self.president_beta.gie, libelle='Beta', montant=9000,
            date_debut=date(2024, 2, 1), date_fin=date(2024, 2, 15)
        )
        Cotisation.objects.create(
            session=session_beta, membre=self.membre_beta
        )

        mars = calculer_statistiques_cotisations(
            self.gie, date(2024, 3, 1), date(2024, 3, 31)
        )
        avril = calculer_statistiques_cotisations(
            self.gie, date(2024, 4, 1), date(2024, 4, 30)
        )

        self.assertEqual(mars['date_situation_retards'], date(2024, 3, 31))
        self.assertEqual(mars['nombre_en_retard'], 2)
        self.assertEqual(mars['montant_en_retard'], Decimal('10000'))
        self.assertEqual(avril['nombre_en_retard'], 1)
        self.assertEqual(avril['montant_en_retard'], Decimal('5000'))


class PretsTestCase(DonneesRapportMixin, TestCase):

    def test_prets_et_remboursements(self):
        # Accordé et décaissé en mars, remboursé en avril
        pret = Pret.objects.create(
            membre=self.membre, montant=60000, statut='rembourse',
            date_approbation=moment(2024, 3, 4),
            date_echeance=date(2024, 6, 5),
            date_remboursement=date(2024, 4, 20)
        )
        creer_operation(self.gie, 'sortie', 60000, moment(2024, 3, 5), pret=pret)
        creer_operation(self.gie, 'entree', 60000, moment(2024, 4, 20), pret=pret)

        # Accordé en mars mais pas encore décaissé
        Pret.objects.create(
            membre=self.secretaire, montant=25000, statut='approuve',
            date_approbation=moment(2024, 3, 31, 23, 59, 59)
        )
        # Simple demande : jamais accordée
        Pret.objects.create(membre=self.tresorier, montant=40000)
        # Autre groupement
        pret_beta = Pret.objects.create(
            membre=self.membre_beta, montant=500000, statut='en_cours',
            date_approbation=moment(2024, 3, 10),
            date_echeance=date(2099, 1, 1)
        )
        creer_operation(
            self.autre_gie, 'sortie', 500000, moment(2024, 3, 10),
            pret=pret_beta
        )

        mars = calculer_statistiques_prets(
            self.gie, date(2024, 3, 1), date(2024, 3, 31)
        )
        avril = calculer_statistiques_prets(
            self.gie, date(2024, 4, 1), date(2024, 4, 30)
        )

        self.assertEqual(mars['nombre_accordes'], 2)
        self.assertEqual(mars['montant_accorde'], Decimal('85000'))
        self.assertEqual(mars['nombre_decaissements'], 1)
        self.assertEqual(mars['montant_decaisse'], Decimal('60000'))
        # Le remboursement n'est pas anticipé : il n'existe qu'en avril.
        self.assertEqual(mars['nombre_remboursements'], 0)
        self.assertEqual(mars['montant_rembourse'], Decimal('0'))

        self.assertEqual(avril['nombre_accordes'], 0)
        self.assertEqual(avril['nombre_remboursements'], 1)
        self.assertEqual(avril['montant_rembourse'], Decimal('60000'))

    def test_prets_actuellement_en_cours_et_en_retard(self):
        Pret.objects.create(
            membre=self.membre, montant=1000, statut='en_cours',
            date_echeance=date(2099, 1, 1)
        )
        # Échéance dépassée mais statut pas encore mis à jour par le CRON
        Pret.objects.create(
            membre=self.secretaire, montant=1000, statut='en_cours',
            date_echeance=date(2024, 1, 1)
        )
        Pret.objects.create(
            membre=self.tresorier, montant=1000, statut='en_retard',
            date_echeance=date(2024, 1, 1)
        )
        Pret.objects.create(
            membre=self.president, montant=1000, statut='rembourse'
        )

        stats = calculer_statistiques_prets(
            self.gie, date(2024, 3, 1), date(2024, 3, 31)
        )

        self.assertEqual(stats['nombre_en_cours'], 1)
        self.assertEqual(stats['nombre_en_retard'], 2)
        self.assertEqual(stats['date_situation'], timezone.localdate())


class ActivitesParticipationTestCase(DonneesRapportMixin, TestCase):

    def creer_activite(self, titre, quand, statut, gie=None):
        gie = gie or self.gie
        return Activite.objects.create(
            gie=gie,
            organisateur=(
                self.president if gie == self.gie else self.president_beta
            ),
            titre=titre,
            date_activite=quand,
            lieu='Siège',
            type_activite='reunion',
            statut=statut
        )

    def test_activites_par_statut(self):
        self.creer_activite('A1', moment(2024, 3, 1, 0, 0, 0), 'terminee')
        self.creer_activite('A2', moment(2024, 3, 10), 'terminee')
        self.creer_activite('A3', moment(2024, 3, 12), 'planifiee')
        self.creer_activite('A4', moment(2024, 3, 20), 'en_cours')
        self.creer_activite('A5', moment(2024, 3, 31, 23, 59, 59), 'annulee')
        # Hors période et autre groupement
        self.creer_activite('B1', moment(2024, 4, 1, 0, 0, 0), 'terminee')
        self.creer_activite('B2', moment(2024, 2, 29, 23, 59, 59), 'terminee')
        self.creer_activite(
            'B3', moment(2024, 3, 15), 'terminee', gie=self.autre_gie
        )

        stats = calculer_statistiques_activites(
            self.gie, date(2024, 3, 1), date(2024, 3, 31)
        )

        self.assertEqual(stats, {
            'total': 5,
            'planifiees': 1,
            'en_cours': 1,
            'terminees': 2,
            'annulees': 1,
        })

    def test_presences_et_absences(self):
        reunion = self.creer_activite('Réunion', moment(2024, 3, 10), 'terminee')
        formation = self.creer_activite(
            'Formation', moment(2024, 3, 20), 'terminee'
        )
        # Aucune présence enregistrée : ne compte ni présent ni absent
        self.creer_activite('Sans appel', moment(2024, 3, 25), 'terminee')
        hors_periode = self.creer_activite(
            'Avril', moment(2024, 4, 10), 'terminee'
        )

        Presence.objects.create(
            activite=reunion, utilisateur=self.president, statut='present'
        )
        Presence.objects.create(
            activite=reunion, utilisateur=self.tresorier, statut='present'
        )
        Presence.objects.create(
            activite=reunion, utilisateur=self.membre, statut='absent'
        )
        # self.secretaire n'a aucun enregistrement pour la réunion.
        Presence.objects.create(
            activite=formation, utilisateur=self.president, statut='present'
        )
        Presence.objects.create(
            activite=hors_periode, utilisateur=self.membre, statut='absent'
        )

        stats = calculer_statistiques_participation(
            self.gie, date(2024, 3, 1), date(2024, 3, 31)
        )

        self.assertEqual(stats['presences'], 3)
        self.assertEqual(stats['absences'], 1)
        self.assertEqual(stats['taux_presence'], Decimal('75.0'))
        self.assertEqual(stats['activites_sans_enregistrement'], 1)
        self.assertEqual(
            [
                (a['titre'], a['presences'], a['absences'], a['taux_presence'])
                for a in stats['par_activite']
            ],
            [
                ('Réunion', 2, 1, Decimal('66.7')),
                ('Formation', 1, 0, Decimal('100.0')),
            ]
        )

    def test_detail_des_activites_par_statut(self):
        planifiee = self.creer_activite('Collecte', moment(2024, 3, 12), 'planifiee')
        self.creer_activite('Atelier', moment(2024, 3, 20), 'en_cours')
        terminee = self.creer_activite('Réunion', moment(2024, 3, 10), 'terminee')
        self.creer_activite('Sans appel', moment(2024, 3, 25), 'terminee')
        # Hors période et autre groupement
        self.creer_activite('Avril', moment(2024, 4, 1, 0, 0, 0), 'terminee')
        self.creer_activite(
            'Beta', moment(2024, 3, 15), 'terminee', gie=self.autre_gie
        )

        Activite.objects.filter(pk=planifiee.pk).update(
            date_creation=moment(2024, 2, 20)
        )
        Presence.objects.create(
            activite=terminee, utilisateur=self.president, statut='present'
        )
        Presence.objects.create(
            activite=terminee, utilisateur=self.tresorier, statut='present'
        )
        Presence.objects.create(
            activite=terminee, utilisateur=self.membre, statut='absent'
        )

        detail = lister_activites_par_statut(
            self.gie, date(2024, 3, 1), date(2024, 3, 31)
        )

        self.assertEqual(
            {statut: [a['titre'] for a in liste] for statut, liste in detail.items()},
            {
                'planifiee': ['Collecte'],
                'en_cours': ['Atelier'],
                'terminee': ['Réunion', 'Sans appel'],
                'annulee': [],
            }
        )

        collecte = detail['planifiee'][0]
        self.assertEqual(collecte['date_planification'], date(2024, 2, 20))
        self.assertEqual(collecte['date_prevue'].date(), date(2024, 3, 12))

        reunion, sans_appel = detail['terminee']
        self.assertEqual(
            (reunion['presences'], reunion['absences'], reunion['taux_presence']),
            (2, 1, Decimal('66.7'))
        )
        # Rien d'enregistré : ni absences supposées, ni taux inventé.
        self.assertEqual(
            (sans_appel['presences'], sans_appel['absences'], sans_appel['taux_presence']),
            (0, 0, None)
        )

    def test_section_activites_du_pdf(self):
        planifiee = self.creer_activite('Collecte', moment(2024, 3, 12), 'planifiee')
        Activite.objects.filter(pk=planifiee.pk).update(
            date_creation=moment(2024, 2, 20)
        )
        terminee = self.creer_activite('Réunion', moment(2024, 3, 10), 'terminee')
        self.creer_activite('Sans appel', moment(2024, 3, 25), 'terminee')
        Presence.objects.create(
            activite=terminee, utilisateur=self.membre, statut='present'
        )

        donnees = collecter_donnees_rapport(self.gie, 'mensuel', 2024, mois=3)
        texte = texte_pdf(generer_rapport_pdf(donnees))

        self.assertIn('Activités de la période (3)', texte)
        self.assertIn('Activités planifiées (1)', texte)
        self.assertIn('Activités en cours (0)', texte)
        self.assertIn('Activités terminées (2)', texte)
        self.assertIn('Activités annulées (0)', texte)
        self.assertEqual(texte.count('Aucune activité pour cette période.'), 2)
        self.assertIn('20/02/2024 Collecte 12/03/2024', texte)
        self.assertIn('Réunion 10/03/2024 1 0 100,0 %', texte)
        self.assertIn('Sans appel 25/03/2024 0 0 Non disponible', texte)
        # Aucune donnée nominative
        self.assertNotIn(self.membre.nom, texte)
        self.assertNotIn(self.membre.prenom, texte)
        # Les autres sections sont toujours présentes
        for section in (
            'Bilan financier', 'Cotisations', 'Prêts', 'Synthèse'
        ):
            self.assertIn(section, texte)
        # La section « Participation » n'existe plus : le détail figure
        # dans le tableau des activités terminées.
        self.assertNotIn('Présences enregistrées', texte)
        self.assertNotIn('Absences enregistrées', texte)

    def test_tableau_d_activites_sur_plusieurs_pages(self):
        for jour in range(1, 29):
            for numero in range(4):
                self.creer_activite(
                    f'Activité {jour}-{numero}',
                    moment(2024, 3, jour, 8 + numero),
                    'terminee'
                )

        donnees = collecter_donnees_rapport(self.gie, 'mensuel', 2024, mois=3)
        pdf = generer_rapport_pdf(donnees)

        with pymupdf.open(stream=pdf, filetype='pdf') as document:
            pages = [
                ' '.join(page.get_text().split()) for page in document
            ]

        pages_avec_entete = [
            page for page in pages if 'Date de planification' in page
        ]
        texte = ' '.join(pages)

        self.assertGreaterEqual(len(pages), 4)
        # L'en-tête est répété sur chaque page où le tableau se poursuit.
        self.assertGreaterEqual(len(pages_avec_entete), 3)
        self.assertIn('Activités terminées (112)', texte)
        self.assertIn('Activité 1-0', texte)
        self.assertIn('Activité 28-3', texte)

    def test_aucune_presence_enregistree(self):
        self.creer_activite('Sans appel', moment(2024, 3, 25), 'terminee')

        stats = calculer_statistiques_participation(
            self.gie, date(2024, 3, 1), date(2024, 3, 31)
        )

        self.assertEqual(stats['presences'], 0)
        self.assertEqual(stats['absences'], 0)
        self.assertIsNone(stats['taux_presence'])

        donnees = collecter_donnees_rapport(self.gie, 'mensuel', 2024, mois=3)
        texte = texte_pdf(generer_rapport_pdf(donnees))

        self.assertIn("le taux de présence n'est pas disponible", texte)
        self.assertIn('Sans appel 25/03/2024 0 0 Non disponible', texte)

    def test_rapport_sans_donnees_nominatives(self):
        reunion = self.creer_activite('Réunion', moment(2024, 3, 10), 'terminee')
        Presence.objects.create(
            activite=reunion, utilisateur=self.membre, statut='present'
        )

        donnees = collecter_donnees_rapport(self.gie, 'mensuel', 2024, mois=3)
        texte = texte_pdf(generer_rapport_pdf(donnees))

        self.assertIn('Réunion', texte)
        self.assertNotIn(self.membre.nom, texte)
        self.assertNotIn(self.membre.prenom, texte)
        self.assertNotIn(self.membre.telephone, texte)
        self.assertNotIn(self.membre.nom, repr(donnees))


# ─── D. Sécurité et E. PDF ────────────────────────────────────────────────────

class RapportApiTestCase(DonneesRapportMixin, TestCase):

    PARAMETRES = {'type_periode': 'mensuel', 'annee': 2024, 'mois': 3}

    def setUp(self):
        self.client = APIClient()

    def obtenir(self, utilisateur=None, **parametres):
        if utilisateur is not None:
            self.client.force_authenticate(user=utilisateur)
        return self.client.get(URL_RAPPORT, parametres or self.PARAMETRES)

    def test_utilisateur_non_authentifie(self):
        reponse = self.obtenir()

        self.assertEqual(reponse.status_code, 401)

    def test_roles_autorises(self):
        for utilisateur in (self.president, self.tresorier):
            with self.subTest(role=utilisateur.role):
                reponse = self.obtenir(utilisateur)
                self.assertEqual(reponse.status_code, 200)

    def test_roles_refuses(self):
        administrateur = Utilisateur.objects.create_user(
            telephone='770000099', nom='Admin', prenom='Plateforme',
            role='administrateur', statut='actif'
        )

        for utilisateur in (self.membre, self.secretaire, administrateur):
            with self.subTest(role=utilisateur.role):
                reponse = self.obtenir(utilisateur)
                self.assertEqual(reponse.status_code, 403)
                self.assertNotEqual(reponse['Content-Type'], 'application/pdf')

    def test_reponse_pdf(self):
        creer_operation(self.gie, 'entree', 150000, moment(2024, 3, 5))

        reponse = self.obtenir(self.tresorier)

        self.assertEqual(reponse.status_code, 200)
        self.assertEqual(reponse['Content-Type'], 'application/pdf')
        self.assertEqual(
            reponse['Content-Disposition'],
            'attachment; filename="rapport-gestion-2024-03.pdf"'
        )
        self.assertTrue(reponse.content.startswith(b'%PDF'))
        self.assertGreater(len(reponse.content), 1000)

        texte = texte_pdf(reponse.content)

        self.assertIn('RAPPORT PÉRIODIQUE DE GESTION DU GROUPEMENT', texte)
        self.assertIn('Groupement Alpha', texte)
        self.assertIn('Mars 2024', texte)
        self.assertIn('du 01/03/2024 au 31/03/2024', texte)
        self.assertIn('150 000 FCFA', texte)
        for section in (
            'Bilan financier', 'Cotisations', 'Prêts', 'Activités',
            'Synthèse'
        ):
            self.assertIn(section, texte)

    def test_noms_de_fichier_trimestriel_et_annuel(self):
        trimestriel = self.obtenir(
            self.president, type_periode='trimestriel', annee=2024, trimestre=4
        )
        annuel = self.obtenir(
            self.president, type_periode='annuel', annee=2024
        )

        self.assertIn('rapport-gestion-2024-T4.pdf', trimestriel['Content-Disposition'])
        self.assertIn('rapport-gestion-2024.pdf', annuel['Content-Disposition'])
        self.assertIn('4e trimestre 2024', texte_pdf(trimestriel.content))
        self.assertIn('du 01/01/2024 au 31/12/2024', texte_pdf(annuel.content))

    def test_periode_actuelle_acceptee(self):
        aujourd_hui = timezone.localdate()

        reponse = self.obtenir(
            self.president,
            type_periode='mensuel',
            annee=aujourd_hui.year,
            mois=aujourd_hui.month
        )

        self.assertEqual(reponse.status_code, 200)

        debut, fin, glissante = obtenir_periode_rapport(
            'mensuel', aujourd_hui.year, mois=aujourd_hui.month
        )
        texte = texte_pdf(reponse.content)

        self.assertTrue(glissante)
        self.assertEqual(fin, aujourd_hui)
        self.assertNotIn('glissante', texte)
        self.assertNotIn("n'est pas terminée", texte)
        self.assertIn(
            f"Période Du {debut.strftime('%d/%m/%Y')} au {fin.strftime('%d/%m/%Y')}",
            texte
        )

    def test_periode_glissante_compte_les_operations_du_mois_precedent(self):
        aujourd_hui = timezone.localdate()
        debut, fin, _ = obtenir_periode_rapport(
            'mensuel', aujourd_hui.year, mois=aujourd_hui.month
        )

        # Premier jour de la période glissante : inclus
        creer_operation(
            self.gie, 'entree', 31000,
            moment(debut.year, debut.month, debut.day, 0, 0, 0)
        )
        # Aujourd'hui : inclus
        creer_operation(self.gie, 'entree', 2000, timezone.now())
        # Veille du début : solde initial uniquement
        veille = debut - timedelta(days=1)
        creer_operation(
            self.gie, 'entree', 500,
            moment(veille.year, veille.month, veille.day, 23, 59, 59)
        )

        donnees = collecter_donnees_rapport(
            self.gie, 'mensuel', aujourd_hui.year, mois=aujourd_hui.month
        )

        self.assertEqual(donnees['periode']['debut'], debut)
        self.assertEqual(donnees['periode']['fin'], aujourd_hui)
        self.assertEqual(donnees['bilan']['solde_initial'], Decimal('500'))
        self.assertEqual(donnees['bilan']['total_entrees'], Decimal('33000'))
        self.assertEqual(donnees['bilan']['solde_final'], Decimal('33500'))

    def test_acces_aux_donnees_d_un_autre_gie_impossible(self):
        creer_operation(self.gie, 'entree', 150000, moment(2024, 3, 5))
        creer_operation(self.autre_gie, 'entree', 424242, moment(2024, 3, 6))

        # Tentatives de ciblage du GIE Alpha par un président du GIE Beta
        reponse = self.obtenir(
            self.president_beta,
            type_periode='mensuel', annee=2024, mois=3,
            gie=self.gie.id, gie_id=self.gie.id, gieId=self.gie.id,
            code=self.gie.code
        )

        self.assertEqual(reponse.status_code, 200)

        texte = texte_pdf(reponse.content)

        self.assertIn('Groupement Beta', texte)
        self.assertIn('424 242 FCFA', texte)
        self.assertNotIn('Groupement Alpha', texte)
        self.assertNotIn('150 000', texte)

    def test_parametres_invalides(self):
        annee_future = timezone.localdate().year + 1

        cas = [
            ({}, 'typePeriode'),
            ({'type_periode': 'hebdomadaire', 'annee': 2024}, 'typePeriode'),
            ({'type_periode': 'annuel'}, 'annee'),
            ({'type_periode': 'annuel', 'annee': 'abc'}, 'annee'),
            ({'type_periode': 'annuel', 'annee': 1999}, 'annee'),
            ({'type_periode': 'annuel', 'annee': 99999}, 'annee'),
            ({'type_periode': 'annuel', 'annee': annee_future}, 'annee'),
            ({'type_periode': 'mensuel', 'annee': 2024}, 'mois'),
            ({'type_periode': 'mensuel', 'annee': 2024, 'mois': 0}, 'mois'),
            ({'type_periode': 'mensuel', 'annee': 2024, 'mois': 13}, 'mois'),
            ({'type_periode': 'mensuel', 'annee': 2024, 'trimestre': 1}, 'mois'),
            ({'type_periode': 'trimestriel', 'annee': 2024}, 'trimestre'),
            ({'type_periode': 'trimestriel', 'annee': 2024, 'trimestre': 5}, 'trimestre'),
        ]

        self.client.force_authenticate(user=self.president)

        # Les clés d'erreur sont en camelCase (renderer du projet).
        for parametres, champ in cas:
            with self.subTest(parametres=parametres):
                reponse = self.client.get(URL_RAPPORT, parametres)
                self.assertEqual(reponse.status_code, 400)
                self.assertIn(champ, reponse.json())
