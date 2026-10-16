from django.test import TestCase
from rest_framework.test import APIClient

from authentication.models import GIE, Utilisateur
from notifications.models import NotificationUtilisateur
from notifications.service import envoyer_notification


URL_LISTE = '/api/notifications/'


class NotificationsApiTestCase(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.gie = GIE.objects.create(
            nom='Groupement Alpha', region='Dakar', type_gie='groupement',
            code='ALPHA', statut='actif'
        )
        cls.president = cls.creer('770000001', 'president')
        cls.tresorier = cls.creer('770000002', 'tresorier')
        cls.membre = cls.creer('770000003', 'membre')

    @classmethod
    def creer(cls, telephone, role):
        return Utilisateur.objects.create_user(
            telephone=telephone, nom='Nom', prenom='Prenom',
            role=role, gie=cls.gie, statut='actif'
        )

    def client_de(self, utilisateur):
        client = APIClient()
        client.force_authenticate(user=utilisateur)
        return client

    def notifier(self, destinataires, titre, module='activites', objet_id=None):
        # Même service que celui appelé par les modules métier.
        # Sans jeton d'appareil enregistré, aucun envoi push n'est tenté.
        return envoyer_notification(
            destinataires=destinataires,
            titre=titre,
            message=f'Message {titre}',
            type_evenement='test',
            module=module,
            objet_id=objet_id,
        )

    def test_liste_des_notifications_de_l_utilisateur(self):
        self.notifier([self.tresorier, self.membre], 'Première', objet_id=7)
        self.notifier([self.tresorier], 'Seconde', module='prets')
        self.notifier([self.membre], 'Pour le membre seulement')

        reponse = self.client_de(self.tresorier).get(URL_LISTE)

        self.assertEqual(reponse.status_code, 200)
        donnees = reponse.json()
        self.assertEqual(donnees['nonLues'], 2)
        # Les plus récentes d'abord, et uniquement celles du trésorier
        self.assertEqual(
            [n['titre'] for n in donnees['notifications']],
            ['Seconde', 'Première']
        )
        premiere = donnees['notifications'][1]
        self.assertEqual(premiere['module'], 'activites')
        self.assertEqual(premiere['objetId'], 7)
        self.assertEqual(premiere['message'], 'Message Première')
        self.assertFalse(premiere['lue'])
        self.assertIn('dateCreation', premiere)

    def test_l_auteur_non_destinataire_ne_recoit_rien(self):
        self.notifier([self.tresorier], 'Pour le trésorier')

        donnees = self.client_de(self.president).get(URL_LISTE).json()

        self.assertEqual(donnees, {'notifications': [], 'nonLues': 0})

    def test_marquer_une_notification_comme_lue(self):
        premiere = self.notifier([self.tresorier, self.membre], 'Première')
        self.notifier([self.tresorier], 'Seconde')
        client = self.client_de(self.tresorier)

        reponse = client.patch(f'{URL_LISTE}{premiere.id}/lire/')

        self.assertEqual(reponse.status_code, 200)
        self.assertEqual(reponse.json()['nonLues'], 1)

        donnees = client.get(URL_LISTE).json()
        etats = {n['titre']: n['lue'] for n in donnees['notifications']}
        self.assertEqual(etats, {'Première': True, 'Seconde': False})

        # La même notification reste non lue pour l'autre destinataire
        self.assertFalse(
            NotificationUtilisateur.objects.get(
                notification=premiere, utilisateur=self.membre
            ).lue
        )

    def test_impossible_de_lire_la_notification_d_un_autre(self):
        notification = self.notifier([self.tresorier], 'Pour le trésorier')

        reponse = self.client_de(self.membre).patch(
            f'{URL_LISTE}{notification.id}/lire/'
        )

        self.assertEqual(reponse.status_code, 404)
        self.assertFalse(
            NotificationUtilisateur.objects.get(
                notification=notification, utilisateur=self.tresorier
            ).lue
        )
        self.assertEqual(
            self.client_de(self.membre).patch(f'{URL_LISTE}999999/lire/').status_code,
            404
        )

    def test_tout_marquer_comme_lu(self):
        self.notifier([self.tresorier, self.membre], 'Première')
        self.notifier([self.tresorier], 'Seconde')

        reponse = self.client_de(self.tresorier).patch(f'{URL_LISTE}tout-lire/')

        self.assertEqual(reponse.status_code, 200)
        self.assertEqual(reponse.json()['nombreMarqueesLues'], 2)
        self.assertEqual(
            self.client_de(self.tresorier).get(URL_LISTE).json()['nonLues'], 0
        )
        # Les notifications du membre ne sont pas touchées
        self.assertEqual(
            self.client_de(self.membre).get(URL_LISTE).json()['nonLues'], 1
        )

    def test_liste_limitee_aux_plus_recentes(self):
        for numero in range(55):
            self.notifier([self.tresorier], f'N{numero}')

        donnees = self.client_de(self.tresorier).get(URL_LISTE).json()

        self.assertEqual(len(donnees['notifications']), 50)
        self.assertEqual(donnees['notifications'][0]['titre'], 'N54')
        # Le compteur porte sur toutes les non lues, pas seulement celles listées
        self.assertEqual(donnees['nonLues'], 55)

    def test_acces_reserve_aux_utilisateurs_connectes(self):
        client = APIClient()

        self.assertEqual(client.get(URL_LISTE).status_code, 401)
        self.assertEqual(client.patch(f'{URL_LISTE}1/lire/').status_code, 401)
        self.assertEqual(client.patch(f'{URL_LISTE}tout-lire/').status_code, 401)
