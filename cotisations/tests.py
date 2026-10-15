from datetime import date

from django.test import TestCase
from rest_framework.test import APIClient

from authentication.models import GIE, Utilisateur
from cotisations.models import Cotisation, SessionCotisation


class IndicateursSessionsTestCase(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.gie = GIE.objects.create(
            nom='Groupement Alpha', region='Dakar', type_gie='groupement',
            code='ALPHA', statut='actif'
        )
        cls.autre_gie = GIE.objects.create(
            nom='Groupement Beta', region='Thiès', type_gie='groupement',
            code='BETA', statut='actif'
        )

        def creer(gie, telephone, role):
            return Utilisateur.objects.create_user(
                telephone=telephone, nom='Nom', prenom='Prenom',
                role=role, gie=gie, statut='actif'
            )

        cls.tresorier = creer(cls.gie, '770000001', 'tresorier')
        cls.membre = creer(cls.gie, '770000002', 'membre')
        cls.membre2 = creer(cls.gie, '770000003', 'membre')
        cls.tresorier_beta = creer(cls.autre_gie, '770000011', 'tresorier')

        cls.session = SessionCotisation.objects.create(
            createur=cls.tresorier, libelle='Octobre', montant=5000,
            date_debut=date(2026, 10, 1), date_fin=date(2026, 10, 31)
        )
        Cotisation.objects.create(session=cls.session, membre=cls.tresorier, statut='paye')
        Cotisation.objects.create(session=cls.session, membre=cls.membre, statut='paye')
        Cotisation.objects.create(session=cls.session, membre=cls.membre2, statut='en_cours')

        SessionCotisation.objects.create(
            createur=cls.tresorier_beta, libelle='Beta', montant=9000,
            date_debut=date(2026, 10, 1), date_fin=date(2026, 10, 31)
        )

    def test_indicateurs_de_la_liste_des_sessions(self):
        client = APIClient()
        client.force_authenticate(user=self.membre)

        reponse = client.get('/api/cotisations/sessions/')

        self.assertEqual(reponse.status_code, 200)
        sessions = reponse.json()
        # Cloisonnement : seule la session du GIE de l'utilisateur
        self.assertEqual([s['libelle'] for s in sessions], ['Octobre'])

        session = sessions[0]
        self.assertEqual(session['nombreMembres'], 3)
        self.assertEqual(session['nombrePaies'], 2)
        self.assertEqual(session['nombreEnAttente'], 1)
        self.assertEqual(int(session['totalAttendu']), 15000)
        self.assertEqual(int(session['totalCollecte']), 10000)

    def test_creation_de_session_inchangee(self):
        client = APIClient()
        client.force_authenticate(user=self.tresorier)

        reponse = client.post(
            '/api/cotisations/sessions/',
            {
                'libelle': 'Novembre', 'montant': 2000,
                'dateDebut': '2026-11-01', 'dateFin': '2026-11-30',
                # Champs calculés : ignorés s'ils sont envoyés
                'totalCollecte': 999999,
            },
            format='json'
        )

        self.assertEqual(reponse.status_code, 201)
        donnees = reponse.json()
        # Une cotisation par membre actif du GIE, aucune payée
        self.assertEqual(donnees['nombreMembres'], 3)
        self.assertEqual(int(donnees['totalAttendu']), 6000)
        self.assertEqual(int(donnees['totalCollecte']), 0)
        self.assertEqual(
            Cotisation.objects.filter(session__libelle='Novembre').count(), 3
        )
