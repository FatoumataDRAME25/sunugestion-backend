from django.test import TestCase
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from authentication.models import GIE, Utilisateur


class AccesOcrTestCase(TestCase):
    """L'analyse d'images est réservée au président et au secrétaire."""

    @classmethod
    def setUpTestData(cls):
        cls.gie = GIE.objects.create(nom='Alpha', region='Dakar', type_gie='groupement', code='ALPHA', statut='actif')
        cls.secretaire = Utilisateur.objects.create_user(
            telephone='770000001', nom='Nom', prenom='Prenom', role='secretaire', gie=cls.gie, statut='actif'
        )
        cls.membre = Utilisateur.objects.create_user(
            telephone='770000002', nom='Nom', prenom='Prenom', role='membre', gie=cls.gie, statut='actif'
        )

    def client_avec_jeton(self, utilisateur=None, jeton=None):
        client = APIClient()
        if utilisateur is not None:
            jeton = str(RefreshToken.for_user(utilisateur).access_token)
        if jeton:
            client.credentials(HTTP_AUTHORIZATION=f'Bearer {jeton}')
        return client

    def test_refuse_sans_connexion(self):
        url = '/api/process-document'
        self.assertEqual(self.client_avec_jeton().post(url, {}, format='multipart').status_code, 401)
        self.assertEqual(
            self.client_avec_jeton(jeton='jeton-invalide').post(url, {}, format='multipart').status_code,
            401
        )

    def test_refuse_pour_un_membre_simple(self):
        reponse = self.client_avec_jeton(self.membre).post('/api/process-document', {}, format='multipart')
        self.assertEqual(reponse.status_code, 403)

    def test_secretaire_autorise(self):
        # Sans fichier : la requête est acceptée puis refusée pour le champ manquant,
        # sans lancer l'analyse d'image
        reponse = self.client_avec_jeton(self.secretaire).post('/api/process-document', {}, format='multipart')
        self.assertEqual(reponse.status_code, 400)
        self.assertIn('file', reponse.json()['detail'])

    def test_verification_de_service_publique(self):
        self.assertEqual(APIClient().get('/ocr/health').status_code, 200)
