from django.test import TestCase
from rest_framework.test import APIClient

from authentication.models import GIE, Utilisateur


class ProfilMembreTestCase(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.gie = GIE.objects.create(
            nom='Groupement Alpha', region='Dakar', type_gie='groupement',
            code='ALPHA', statut='actif'
        )
        cls.membre = Utilisateur.objects.create_user(
            telephone='770000002', nom='Fall', prenom='Moussa',
            role='membre', gie=cls.gie, statut='actif', password='1234'
        )

    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(user=self.membre)

    def changer_pin(self, **donnees):
        # Mêmes clés camelCase que celles envoyées par le frontend
        return self.client.post(
            '/api/membres/membres/changer-pin/', donnees, format='json'
        )

    def test_changement_de_pin(self):
        reponse = self.changer_pin(
            pinActuel='1234', nouveauPin='5678', confirmationPin='5678'
        )

        self.assertEqual(reponse.status_code, 200)
        self.membre.refresh_from_db()
        self.assertTrue(self.membre.check_password('5678'))

    def test_pin_actuel_incorrect(self):
        reponse = self.changer_pin(
            pinActuel='0000', nouveauPin='5678', confirmationPin='5678'
        )

        self.assertEqual(reponse.status_code, 400)
        self.assertIn('incorrect', reponse.json()['erreur'])
        self.membre.refresh_from_db()
        self.assertTrue(self.membre.check_password('1234'))

    def test_champ_manquant(self):
        reponse = self.changer_pin(pinActuel='1234', nouveauPin='5678')

        self.assertEqual(reponse.status_code, 400)
        self.assertIn('obligatoires', reponse.json()['erreur'])

    def test_telephone_non_modifiable(self):
        reponse = self.client.patch(
            f'/api/membres/membres/{self.membre.id}/',
            {'telephone': '781112233', 'email': 'moussa@example.com'},
            format='json'
        )

        self.assertEqual(reponse.status_code, 200)
        self.membre.refresh_from_db()
        self.assertEqual(self.membre.telephone, '770000002')
        self.assertEqual(self.membre.email, 'moussa@example.com')


class ChangerPinAdminTestCase(TestCase):

    def test_changement_de_pin_administrateur(self):
        administrateur = Utilisateur.objects.create_user(
            telephone='770000099', nom='Admin', prenom='Plateforme',
            role='administrateur', statut='actif', password='1234'
        )
        client = APIClient()
        client.force_authenticate(user=administrateur)

        reponse = client.post(
            '/api/auth/changer-pin/',
            {'pinActuel': '1234', 'nouveauPin': '5678', 'confirmationPin': '5678'},
            format='json'
        )

        self.assertEqual(reponse.status_code, 200)
        administrateur.refresh_from_db()
        self.assertTrue(administrateur.check_password('5678'))
