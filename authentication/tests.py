from django.test import TestCase

from datetime import timedelta

from django.utils import timezone

from .models import Utilisateur


class VerrouillagePinTestCase(TestCase):

    def setUp(self):
        """Créer un utilisateur de test."""
        self.utilisateur = Utilisateur.objects.create_user(
            telephone="770000001",
            nom="Test",
            prenom="Utilisateur",
            role="membre",
            password="1234",
            statut="actif",
        )

    def test_quatre_erreurs_ne_verrouillent_pas_le_compte(self):
        """Le compte reste déverrouillé après quatre erreurs."""

        for _ in range(4):
            valide, message = self.utilisateur.verifier_pin("9999")
            self.assertFalse(valide)

        self.utilisateur.refresh_from_db()

        self.assertEqual(self.utilisateur.tentatives_pin, 4)
        self.assertFalse(self.utilisateur.verrouille)

        print("OK : quatre erreurs, compte non verrouillé.")

    def test_cinquieme_erreur_verrouille_le_compte(self):
        """La cinquième erreur déclenche le verrouillage."""

        for _ in range(5):
            valide, message = self.utilisateur.verifier_pin("9999")

        self.utilisateur.refresh_from_db()

        self.assertFalse(valide)
        self.assertTrue(self.utilisateur.verrouille)
        self.assertEqual(self.utilisateur.tentatives_pin, 5)
        self.assertIsNotNone(self.utilisateur.date_verrouillage)

        print("OK : cinquième erreur, compte verrouillé.")

    def test_bon_pin_refuse_pendant_le_verrouillage(self):
        """Le bon PIN ne permet pas de contourner le verrouillage."""

        for _ in range(5):
            self.utilisateur.verifier_pin("9999")

        valide, message = self.utilisateur.verifier_pin("1234")

        self.assertFalse(valide)
        self.assertIn("verrouillé", message.lower())

        print("OK : connexion refusée pendant le verrouillage.")

    def test_deverrouillage_apres_quinze_minutes(self):
        """Le compte se déverrouille après expiration du délai."""

        for _ in range(5):
            self.utilisateur.verifier_pin("9999")

        # Simuler un verrouillage datant de 16 minutes.
        self.utilisateur.date_verrouillage = (
            timezone.now() - timedelta(minutes=16)
        )
        self.utilisateur.save(update_fields=["date_verrouillage"])

        valide, message = self.utilisateur.verifier_pin("1234")

        self.utilisateur.refresh_from_db()

        self.assertTrue(valide)
        self.assertFalse(self.utilisateur.verrouille)
        self.assertEqual(self.utilisateur.tentatives_pin, 0)
        self.assertIsNone(self.utilisateur.date_verrouillage)

        print("OK : déverrouillage automatique après expiration.")

    def test_compteur_reinitialise_apres_connexion_reussie(self):
        """Une connexion réussie remet le compteur à zéro."""

        self.utilisateur.verifier_pin("9999")
        self.utilisateur.verifier_pin("9999")

        valide, message = self.utilisateur.verifier_pin("1234")

        self.utilisateur.refresh_from_db()

        self.assertTrue(valide)
        self.assertEqual(self.utilisateur.tentatives_pin, 0)

        print("OK : compteur réinitialisé après connexion réussie.")


# ──────────────────────────────────────────────────────────────────────────
# Endpoints d'administration et groupements désactivés
# ──────────────────────────────────────────────────────────────────────────

from rest_framework.test import APIClient

from .models import GIE


ENDPOINTS_ADMIN = [
    '/api/auth/liste-gies/',
    '/api/auth/gies/statistiques/',
    '/api/auth/gies/evolution/',
    '/api/auth/gies/repartition-secteur/',
]


class EndpointsAdministrationTestCase(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.gie = GIE.objects.create(
            nom='Groupement Alpha', region='Dakar', type_gie='groupement',
            code='ALPHA', statut='actif'
        )
        cls.administrateur = Utilisateur.objects.create_user(
            telephone='770000099', nom='Admin', prenom='Plateforme',
            role='administrateur', statut='actif'
        )
        cls.president = Utilisateur.objects.create_user(
            telephone='770000001', nom='Diop', prenom='Awa',
            role='president', gie=cls.gie, statut='actif'
        )

    def client_de(self, utilisateur=None):
        client = APIClient()
        if utilisateur is not None:
            client.force_authenticate(user=utilisateur)
        return client

    def test_reserves_a_l_administrateur(self):
        url_detail = f'/api/auth/gies/{self.gie.id}/'

        for url in ENDPOINTS_ADMIN + [url_detail]:
            with self.subTest(url=url):
                self.assertEqual(self.client_de().get(url).status_code, 401)
                self.assertEqual(self.client_de(self.president).get(url).status_code, 403)
                self.assertEqual(self.client_de(self.administrateur).get(url).status_code, 200)

    def test_modification_d_un_gie_impossible_sans_etre_administrateur(self):
        url = f'/api/auth/gies/{self.gie.id}/'

        for utilisateur in (None, self.president):
            with self.subTest(utilisateur=utilisateur):
                reponse = self.client_de(utilisateur).patch(url, {'statut': 'inactif'}, format='json')
                self.assertIn(reponse.status_code, (401, 403))
                self.gie.refresh_from_db()
                self.assertEqual(self.gie.statut, 'actif')

        reponse = self.client_de(self.administrateur).patch(url, {'statut': 'inactif'}, format='json')
        self.assertEqual(reponse.status_code, 200)
        self.gie.refresh_from_db()
        self.assertEqual(self.gie.statut, 'inactif')

    def test_inscription_toujours_publique(self):
        # Création d'un GIE à l'inscription : reste accessible sans connexion
        reponse = self.client_de().post('/api/auth/creer-gie/', {}, format='json')
        self.assertEqual(reponse.status_code, 400)


class GieDesactiveTestCase(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.gie = GIE.objects.create(
            nom='Groupement Alpha', region='Dakar', type_gie='groupement',
            code='ALPHA', statut='actif'
        )
        cls.president = Utilisateur.objects.create_user(
            telephone='770000001', nom='Diop', prenom='Awa',
            role='president', gie=cls.gie, statut='actif', password='1234'
        )

    def desactiver(self):
        GIE.objects.filter(pk=self.gie.pk).update(statut='inactif')
        self.president.refresh_from_db()

    def connexion(self):
        return APIClient().post(
            '/api/auth/connexion/',
            {'telephone': self.president.telephone, 'pin': '1234'},
            format='json'
        )

    def test_gie_actif_fonctionne_normalement(self):
        client = APIClient()
        client.force_authenticate(user=self.president)

        self.assertEqual(client.get('/api/membres/membres/').status_code, 200)
        self.assertEqual(self.connexion().status_code, 200)

    def test_membres_d_un_gie_desactive_bloques(self):
        self.desactiver()
        client = APIClient()
        client.force_authenticate(user=self.president)

        for url in ('/api/membres/membres/', '/api/gie/infos/', '/api/prets/', '/api/historiques/solde/', '/api/diagnostic/'):
            with self.subTest(url=url):
                reponse = client.get(url)
                self.assertEqual(reponse.status_code, 403)
                self.assertIn('désactivé', reponse.json()['detail'])

    def test_connexion_refusee_pour_un_gie_desactive(self):
        self.desactiver()

        reponse = self.connexion()

        self.assertEqual(reponse.status_code, 400)
        self.assertIn('désactivé', str(reponse.json()))
        self.assertNotIn('tokens', reponse.json())

    def test_reactivation_retablit_l_acces(self):
        self.desactiver()
        GIE.objects.filter(pk=self.gie.pk).update(statut='actif')
        self.president.refresh_from_db()

        client = APIClient()
        client.force_authenticate(user=self.president)
        self.assertEqual(client.get('/api/membres/membres/').status_code, 200)


# ──────────────────────────────────────────────────────────────────────────
# Sécurité de la connexion et de l'inscription
# ──────────────────────────────────────────────────────────────────────────

from unittest.mock import patch

from django.core.cache import cache
from rest_framework.throttling import ScopedRateThrottle


class OtpTestCase(TestCase):

    def setUp(self):
        cache.clear()
        self.president = Utilisateur.objects.create_user(
            telephone='770000050', nom='Diop', prenom='Awa', role='president',
            statut='en_attente', email='awa@example.com'
        )

    def test_code_a_six_chiffres(self):
        code = self.president.generer_otp()
        self.assertTrue(code.isdigit())
        self.assertEqual(len(code), 6)

    def test_code_invalide_apres_cinq_erreurs(self):
        code = self.president.generer_otp()
        faux = '000000' if code != '000000' else '111111'

        for _ in range(4):
            valide, message = self.president.verifier_otp(faux)
            self.assertFalse(valide)
            self.assertIn('incorrect', message)

        valide, message = self.president.verifier_otp(faux)
        self.assertFalse(valide)
        self.assertIn('Trop de tentatives', message)

        # Même le bon code ne fonctionne plus : il faut en demander un nouveau
        valide, _ = self.president.verifier_otp(code)
        self.assertFalse(valide)

    def test_nouveau_code_remet_le_compteur_a_zero(self):
        self.president.generer_otp()
        for _ in range(4):
            self.president.verifier_otp('000000' if self.president.otp != '000000' else '111111')

        code = self.president.generer_otp()
        valide, _ = self.president.verifier_otp(code)
        self.assertTrue(valide)


class ConnexionSecuriteTestCase(TestCase):

    def setUp(self):
        cache.clear()

    def tearDown(self):
        cache.clear()

    def connexion(self, telephone='779999999', pin='1234'):
        return APIClient().post('/api/auth/connexion/', {'telephone': telephone, 'pin': pin}, format='json')

    def test_numero_inconnu_message_generique(self):
        reponse = self.connexion()

        self.assertEqual(reponse.status_code, 400)
        self.assertIn('Numéro de téléphone ou code PIN incorrect', str(reponse.json()))
        self.assertNotIn('introuvable', str(reponse.json()))

    def test_trop_de_tentatives_de_connexion(self):
        with patch.dict(ScopedRateThrottle.THROTTLE_RATES, {'connexion': '3/min'}):
            codes = [self.connexion().status_code for _ in range(4)]

        self.assertEqual(codes[:3], [400, 400, 400])
        self.assertEqual(codes[3], 429)


class CreationGieValidationTestCase(TestCase):

    def creer(self, **donnees):
        corps = {'nom': 'Groupement Test', 'region': 'Dakar', 'typeGie': 'groupement', **donnees}
        return APIClient().post('/api/auth/creer-gie/', corps, format='json')

    def test_nom_avec_balises_refuse(self):
        reponse = self.creer(nom='<script>alert(1)</script>')

        self.assertEqual(reponse.status_code, 400)
        self.assertIn('nom', reponse.json())
        self.assertFalse(GIE.objects.filter(nom__contains='script').exists())

    def test_telephone_avec_lettres_refuse(self):
        reponse = self.creer(telephone='77abc1234')

        self.assertEqual(reponse.status_code, 400)
        self.assertIn('telephone', reponse.json())

    def test_creation_valide_avec_ou_sans_telephone(self):
        self.assertEqual(self.creer(nom='Avec numéro', telephone='77 123 45 67').status_code, 201)
        self.assertEqual(GIE.objects.get(nom='Avec numéro').telephone, '771234567')
        self.assertEqual(self.creer(nom='Sans numéro').status_code, 201)
