from django.test import TestCase
from rest_framework.test import APIClient

from authentication.models import GIE, Utilisateur


class GieInfosTestCase(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.gie = GIE.objects.create(
            nom='Groupement Alpha', region='Dakar', type_gie='groupement',
            telephone='338000000', code='ALPHA', statut='actif'
        )
        cls.autre_gie = GIE.objects.create(
            nom='Groupement Beta', region='Thiès', type_gie='association',
            code='BETA', statut='actif'
        )
        cls.president = Utilisateur.objects.create_user(
            telephone='770000001', nom='Diop', prenom='Awa',
            role='president', gie=cls.gie, statut='actif'
        )
        cls.membre = Utilisateur.objects.create_user(
            telephone='770000002', nom='Fall', prenom='Moussa',
            role='membre', gie=cls.gie, statut='actif'
        )

    def setUp(self):
        self.client = APIClient()

    def test_un_membre_recoit_les_infos_de_son_gie(self):
        self.client.force_authenticate(user=self.membre)

        reponse = self.client.get('/api/gie/infos/')

        self.assertEqual(reponse.status_code, 200)
        donnees = reponse.json()
        self.assertEqual(donnees['nom'], 'Groupement Alpha')
        self.assertEqual(donnees['region'], 'Dakar')
        self.assertEqual(donnees['typeGie'], 'groupement')
        self.assertEqual(donnees['telephone'], '338000000')
        self.assertEqual(donnees['code'], 'ALPHA')

    def test_le_president_peut_modifier_les_infos(self):
        self.client.force_authenticate(user=self.president)

        reponse = self.client.patch(
            '/api/gie/infos/',
            {'nom': 'Groupement Alpha 2', 'typeGie': 'association'},
            format='json'
        )

        self.assertEqual(reponse.status_code, 200)
        self.gie.refresh_from_db()
        self.assertEqual(self.gie.nom, 'Groupement Alpha 2')
        self.assertEqual(self.gie.type_gie, 'association')
        # L'autre groupement n'est pas touché
        self.autre_gie.refresh_from_db()
        self.assertEqual(self.autre_gie.nom, 'Groupement Beta')

    def test_un_membre_ne_peut_pas_modifier(self):
        self.client.force_authenticate(user=self.membre)

        reponse = self.client.patch(
            '/api/gie/infos/', {'nom': 'Piraté'}, format='json'
        )

        self.assertEqual(reponse.status_code, 403)
