import io
import os
import shutil
import tempfile

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from PIL import Image
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

    def test_nom_avec_balises_refuse(self):
        self.client.force_authenticate(user=self.president)

        reponse = self.client.patch(
            '/api/gie/infos/', {'nom': '<script>alert(1)</script>'}, format='json'
        )

        self.assertEqual(reponse.status_code, 400)
        self.gie.refresh_from_db()
        self.assertEqual(self.gie.nom, 'Groupement Alpha')

    def test_telephone_invalide_refuse(self):
        self.client.force_authenticate(user=self.president)

        for telephone in ('77abc1234', '12345', '7712345678'):
            reponse = self.client.patch(
                '/api/gie/infos/', {'telephone': telephone}, format='json'
            )
            self.assertEqual(reponse.status_code, 400, telephone)

        self.gie.refresh_from_db()
        self.assertEqual(self.gie.telephone, '338000000')

    def test_telephone_fixe_mobile_avec_espaces_ou_vide_accepte(self):
        self.client.force_authenticate(user=self.president)

        for envoye, enregistre in (('77 123 45 67', '771234567'), ('338123456', '338123456'), ('', '')):
            reponse = self.client.patch(
                '/api/gie/infos/', {'telephone': envoye}, format='json'
            )
            self.assertEqual(reponse.status_code, 200, envoye)
            self.gie.refresh_from_db()
            self.assertEqual(self.gie.telephone, enregistre)


def image_envoyee(largeur=300, hauteur=200, format_image='PNG', mode='RGBA', nom='logo.png'):
    tampon = io.BytesIO()
    Image.new(mode, (largeur, hauteur), (30, 58, 95) if mode == 'RGB' else (30, 58, 95, 128)).save(tampon, format=format_image)
    return SimpleUploadedFile(nom, tampon.getvalue(), content_type=f'image/{format_image.lower()}')


class LogoGieTestCase(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.gie = GIE.objects.create(
            nom='Groupement Alpha', region='Dakar', type_gie='groupement',
            code='ALPHA', statut='actif'
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
        # Fichiers écrits dans un dossier temporaire, supprimé après chaque test
        self.dossier_media = tempfile.mkdtemp()
        reglage = override_settings(MEDIA_ROOT=self.dossier_media)
        reglage.enable()
        self.addCleanup(reglage.disable)
        self.addCleanup(shutil.rmtree, self.dossier_media, ignore_errors=True)
        self.client = APIClient()

    def envoyer(self, fichier, utilisateur=None):
        self.client.force_authenticate(user=utilisateur or self.president)
        return self.client.patch('/api/gie/infos/', {'logo': fichier}, format='multipart')

    def chemin(self, nom):
        return os.path.join(self.dossier_media, nom)

    def test_le_president_envoie_un_logo_reencode_en_webp(self):
        reponse = self.envoyer(image_envoyee())

        self.assertEqual(reponse.status_code, 200)
        self.gie.refresh_from_db()
        self.assertTrue(self.gie.logo.name.startswith('gie/logos/'))
        self.assertEqual(reponse.json()['logo'], '/media/' + self.gie.logo.name)
        with Image.open(self.chemin(self.gie.logo.name)) as image:
            self.assertEqual(image.format, 'WEBP')
            self.assertEqual(image.size, (300, 200))
            self.assertEqual(image.mode, 'RGBA')  # transparence conservée

        # Visible par les membres
        self.client.force_authenticate(user=self.membre)
        self.assertEqual(self.client.get('/api/gie/infos/').json()['logo'], '/media/' + self.gie.logo.name)

    def test_grande_image_reduite_a_512_pixels(self):
        self.assertEqual(self.envoyer(image_envoyee(2000, 1000, 'JPEG', 'RGB', 'photo.jpg')).status_code, 200)

        self.gie.refresh_from_db()
        with Image.open(self.chemin(self.gie.logo.name)) as image:
            self.assertEqual(image.size, (512, 256))

    def test_un_membre_ne_peut_pas_changer_le_logo(self):
        self.assertEqual(self.envoyer(image_envoyee(), self.membre).status_code, 403)

        self.gie.refresh_from_db()
        self.assertFalse(self.gie.logo)

    def test_fichier_qui_n_est_pas_une_image_refuse(self):
        faux = SimpleUploadedFile('logo.png', b'<script>alert(1)</script>', content_type='image/png')

        reponse = self.envoyer(faux)

        self.assertEqual(reponse.status_code, 400)
        self.assertIn("n'est pas une image valide", reponse.json()['logo'][0])

    def test_format_non_accepte_refuse(self):
        reponse = self.envoyer(image_envoyee(format_image='GIF', mode='RGB', nom='logo.gif'))

        self.assertEqual(reponse.status_code, 400)
        self.assertIn('JPEG, PNG ou WebP', reponse.json()['logo'][0])

    def test_fichier_de_plus_de_2_mo_refuse(self):
        lourd = SimpleUploadedFile('logo.png', b'0' * (2 * 1024 * 1024 + 1), content_type='image/png')

        reponse = self.envoyer(lourd)

        self.assertEqual(reponse.status_code, 400)
        self.assertIn('2 Mo', reponse.json()['logo'][0])

    def test_image_aux_dimensions_demesurees_refusee(self):
        # Fichier léger (couleur unie) mais 30 millions de pixels une fois décodé
        reponse = self.envoyer(image_envoyee(6000, 5000, 'PNG', 'RGB'))

        self.assertEqual(reponse.status_code, 400)
        self.assertIn('trop grande', reponse.json()['logo'][0])

    def test_nouveau_logo_supprime_l_ancien_fichier(self):
        self.envoyer(image_envoyee())
        self.gie.refresh_from_db()
        ancien = self.gie.logo.name

        with self.captureOnCommitCallbacks(execute=True):
            self.assertEqual(self.envoyer(image_envoyee(100, 100)).status_code, 200)

        self.gie.refresh_from_db()
        self.assertNotEqual(self.gie.logo.name, ancien)
        self.assertFalse(os.path.exists(self.chemin(ancien)))
        self.assertTrue(os.path.exists(self.chemin(self.gie.logo.name)))

    def test_retirer_le_logo(self):
        self.envoyer(image_envoyee())
        self.gie.refresh_from_db()
        ancien = self.gie.logo.name

        with self.captureOnCommitCallbacks(execute=True):
            reponse = self.client.patch('/api/gie/infos/', {'logo': None}, format='json')

        self.assertEqual(reponse.status_code, 200)
        self.assertIsNone(reponse.json()['logo'])
        self.assertFalse(os.path.exists(self.chemin(ancien)))

    def test_modifier_le_nom_ne_touche_pas_au_logo(self):
        self.envoyer(image_envoyee())
        self.gie.refresh_from_db()
        logo = self.gie.logo.name

        with self.captureOnCommitCallbacks(execute=True):
            self.client.patch('/api/gie/infos/', {'nom': 'Nouveau nom'}, format='json')

        self.gie.refresh_from_db()
        self.assertEqual(self.gie.logo.name, logo)
        self.assertTrue(os.path.exists(self.chemin(logo)))
