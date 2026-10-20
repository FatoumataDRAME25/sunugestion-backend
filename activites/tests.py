from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from activites.models import Activite
from authentication.models import GIE, Utilisateur


class CloisonnementActivitesTestCase(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.gie = GIE.objects.create(nom='Alpha', region='Dakar', type_gie='groupement', code='ALPHA', statut='actif')
        cls.autre_gie = GIE.objects.create(nom='Beta', region='Thiès', type_gie='groupement', code='BETA', statut='actif')
        cls.president = Utilisateur.objects.create_user(
            telephone='770000001', nom='Nom', prenom='Prenom', role='president', gie=cls.gie, statut='actif'
        )
        cls.membre = Utilisateur.objects.create_user(
            telephone='770000002', nom='Nom', prenom='Prenom', role='membre', gie=cls.gie, statut='actif'
        )
        cls.president_beta = Utilisateur.objects.create_user(
            telephone='770000011', nom='Nom', prenom='Prenom', role='president', gie=cls.autre_gie, statut='actif'
        )

        def activite(gie, organisateur, titre):
            return Activite.objects.create(
                gie=gie, organisateur=organisateur, titre=titre,
                date_activite=timezone.now() + timezone.timedelta(days=3),
                lieu='Siège', type_activite='reunion'
            )

        cls.activite = activite(cls.gie, cls.president, 'Réunion Alpha')
        cls.activite_beta = activite(cls.autre_gie, cls.president_beta, 'Réunion Beta')

    def client_de(self, utilisateur):
        client = APIClient()
        client.force_authenticate(user=utilisateur)
        return client

    def test_liste_et_detail_limites_au_groupement(self):
        client = self.client_de(self.membre)

        liste = client.get('/api/activites/activites/').json()
        activites = liste if isinstance(liste, list) else liste.get('results', [])
        titres = [a['titre'] for a in activites]

        self.assertIn('Réunion Alpha', titres)
        self.assertNotIn('Réunion Beta', titres)
        self.assertEqual(client.get(f'/api/activites/activites/{self.activite_beta.id}/').status_code, 404)

    def test_un_membre_ne_peut_pas_planifier(self):
        reponse = self.client_de(self.membre).post('/api/activites/activites/', {
            'titre': 'Test', 'dateActivite': (timezone.now() + timezone.timedelta(days=5)).isoformat(),
            'lieu': 'Siège', 'typeActivite': 'reunion'
        }, format='json')

        self.assertEqual(reponse.status_code, 403)

    def test_un_president_ne_peut_pas_annuler_l_activite_d_un_autre_groupement(self):
        reponse = self.client_de(self.president).post(
            f'/api/activites/activites/{self.activite_beta.id}/annuler/'
        )

        self.assertEqual(reponse.status_code, 404)
        self.activite_beta.refresh_from_db()
        self.assertEqual(self.activite_beta.statut, 'planifiee')


class CycleActiviteTestCase(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.gie = GIE.objects.create(nom='Alpha', region='Dakar', type_gie='groupement', code='ALPHA', statut='actif')
        cls.president = Utilisateur.objects.create_user(
            telephone='770000001', nom='Nom', prenom='Prenom', role='president', gie=cls.gie, statut='actif'
        )

    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(user=self.president)

    def creer(self, quand):
        return Activite.objects.create(
            gie=self.gie, organisateur=self.president, titre='Assemblée',
            date_activite=quand, lieu='Siège', type_activite='reunion'
        )

    def test_demarrer_puis_terminer_le_jour_prevu(self):
        activite = self.creer(timezone.now())

        reponse = self.client.post(f'/api/activites/activites/{activite.id}/demarrer/')
        self.assertEqual(reponse.status_code, 200)
        activite.refresh_from_db()
        self.assertEqual(activite.statut, 'en_cours')

        reponse = self.client.post(
            f'/api/activites/activites/{activite.id}/terminer/',
            {'compteRendu': 'Bilan adopté.'}, format='json'
        )
        self.assertEqual(reponse.status_code, 200)
        activite.refresh_from_db()
        self.assertEqual(activite.statut, 'terminee')

    def test_demarrer_un_autre_jour_refuse(self):
        activite = self.creer(timezone.now() + timezone.timedelta(days=2))

        reponse = self.client.post(f'/api/activites/activites/{activite.id}/demarrer/')

        self.assertEqual(reponse.status_code, 400)
        activite.refresh_from_db()
        self.assertEqual(activite.statut, 'planifiee')


class HistoriqueActiviteTestCase(TestCase):
    """Une activité terminée ou annulée ne doit plus être réécrite."""

    @classmethod
    def setUpTestData(cls):
        cls.gie = GIE.objects.create(nom='Alpha', region='Dakar', type_gie='groupement', code='ALPHA', statut='actif')
        cls.president = Utilisateur.objects.create_user(
            telephone='770000001', nom='Nom', prenom='Prenom', role='president', gie=cls.gie, statut='actif'
        )

    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(user=self.president)

    def creer(self, statut, jours=3):
        return Activite.objects.create(
            gie=self.gie, organisateur=self.president, titre='Assemblée', statut=statut,
            date_activite=timezone.now() + timezone.timedelta(days=jours), lieu='Siège', type_activite='reunion'
        )

    def url(self, activite):
        return f'/api/activites/activites/{activite.id}/'

    def test_activite_terminee_ni_modifiable_ni_supprimable(self):
        activite = self.creer('terminee', jours=-2)

        self.assertEqual(self.client.patch(self.url(activite), {'titre': 'Autre'}, format='json').status_code, 400)
        self.assertEqual(self.client.delete(self.url(activite)).status_code, 400)
        activite.refresh_from_db()
        self.assertEqual(activite.titre, 'Assemblée')

    def test_activite_annulee_non_modifiable_mais_supprimable(self):
        activite = self.creer('annulee')

        self.assertEqual(self.client.patch(self.url(activite), {'titre': 'Autre'}, format='json').status_code, 400)
        self.assertEqual(self.client.delete(self.url(activite)).status_code, 204)
        self.assertFalse(Activite.objects.filter(pk=activite.pk).exists())

    def test_activite_planifiee_reste_modifiable_et_supprimable(self):
        activite = self.creer('planifiee')

        self.assertEqual(self.client.patch(self.url(activite), {'titre': 'Nouveau titre'}, format='json').status_code, 200)
        activite.refresh_from_db()
        self.assertEqual(activite.titre, 'Nouveau titre')
        self.assertEqual(self.client.delete(self.url(activite)).status_code, 204)
