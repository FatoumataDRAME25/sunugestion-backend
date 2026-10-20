from django.test import TestCase
from rest_framework.test import APIClient

from authentication.models import GIE, Utilisateur
from historiques.models import HistoriqueOperation


class CaisseTestCase(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.gie = GIE.objects.create(nom='Alpha', region='Dakar', type_gie='groupement', code='ALPHA', statut='actif')
        cls.autre_gie = GIE.objects.create(nom='Beta', region='Thiès', type_gie='groupement', code='BETA', statut='actif')
        cls.tresorier = Utilisateur.objects.create_user(
            telephone='770000001', nom='Nom', prenom='Prenom', role='tresorier', gie=cls.gie, statut='actif'
        )
        cls.membre = Utilisateur.objects.create_user(
            telephone='770000002', nom='Nom', prenom='Prenom', role='membre', gie=cls.gie, statut='actif'
        )
        HistoriqueOperation.objects.create(gie=cls.gie, type_operation='entree', montant=100000, libelle='Caisse')
        cls.operation_beta = HistoriqueOperation.objects.create(
            gie=cls.autre_gie, type_operation='entree', montant=900000, libelle='Caisse Beta'
        )

    def client_de(self, utilisateur):
        client = APIClient()
        client.force_authenticate(user=utilisateur)
        return client

    def sortie(self, utilisateur, montant):
        return self.client_de(utilisateur).post(
            '/api/historiques/operations/',
            {'typeOperation': 'sortie', 'montant': montant, 'libelle': 'Achat de matériel'},
            format='json'
        )

    def test_sortie_manuelle_dans_la_limite_du_solde(self):
        reponse = self.sortie(self.tresorier, 1000)

        self.assertEqual(reponse.status_code, 201)
        self.assertEqual(
            int(self.client_de(self.tresorier).get('/api/historiques/solde/').json()['solde']), 99000
        )

    def test_sortie_superieure_au_solde_refusee(self):
        reponse = self.sortie(self.tresorier, 1000000)

        self.assertEqual(reponse.status_code, 400)
        self.assertIn('montant', reponse.json())

    def test_seul_le_tresorier_enregistre_une_operation(self):
        self.assertEqual(self.sortie(self.membre, 1000).status_code, 403)

    def test_operations_d_un_autre_groupement_invisibles(self):
        client = self.client_de(self.membre)

        liste = client.get('/api/historiques/').json()
        operations = liste if isinstance(liste, list) else liste.get('results', [])
        self.assertNotIn(self.operation_beta.id, [o['id'] for o in operations])
        self.assertEqual(client.get(f'/api/historiques/{self.operation_beta.id}/').status_code, 404)
        self.assertEqual(int(client.get('/api/historiques/solde/').json()['solde']), 100000)
