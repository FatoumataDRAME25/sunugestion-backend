from unittest.mock import patch

from django.test import TestCase
from rest_framework.test import APIClient

from authentication.models import GIE, Utilisateur
from historiques.models import HistoriqueOperation
from paiements.paydunya_service import (
    PayDunyaNetworkError, construire_url_annulation, construire_url_retour, origine_requete,
)
from prets.models import Pret, ReglePret


class PretsMixin:

    @classmethod
    def setUpTestData(cls):
        cls.gie = GIE.objects.create(nom='Alpha', region='Dakar', type_gie='groupement', code='ALPHA', statut='actif')
        cls.autre_gie = GIE.objects.create(nom='Beta', region='Thiès', type_gie='groupement', code='BETA', statut='actif')

        def creer(gie, telephone, role):
            return Utilisateur.objects.create_user(
                telephone=telephone, nom='Nom', prenom='Prenom', role=role, gie=gie, statut='actif'
            )

        cls.president = creer(cls.gie, '770000001', 'president')
        cls.tresorier = creer(cls.gie, '770000002', 'tresorier')
        cls.membre = creer(cls.gie, '770000003', 'membre')
        cls.president_beta = creer(cls.autre_gie, '770000011', 'president')
        cls.tresorier_beta = creer(cls.autre_gie, '770000012', 'tresorier')
        cls.membre_beta = creer(cls.autre_gie, '770000013', 'membre')

        for gie in (cls.gie, cls.autre_gie):
            ReglePret.objects.create(gie=gie, montant_max=100000, duree_max_mois=6)
            HistoriqueOperation.objects.create(gie=gie, type_operation='entree', montant=500000, libelle='Caisse')

    def client_de(self, utilisateur):
        client = APIClient()
        client.force_authenticate(user=utilisateur)
        return client


class CloisonnementPretsTestCase(PretsMixin, TestCase):

    def test_approbation_d_un_pret_d_un_autre_groupement_impossible(self):
        pret = Pret.objects.create(membre=self.membre_beta, montant=20000)

        reponse = self.client_de(self.president).post(
            f'/api/prets/{pret.id}/approuver/', {'dureeMois': 3}, format='json'
        )

        self.assertEqual(reponse.status_code, 404)
        pret.refresh_from_db()
        self.assertEqual(pret.statut, 'en_attente')

    def test_decaissement_d_un_pret_d_un_autre_groupement_impossible(self):
        pret = Pret.objects.create(membre=self.membre_beta, montant=20000, statut='approuve', duree_mois=3)

        reponse = self.client_de(self.tresorier).post(
            f'/api/prets/{pret.id}/decaisser/', {'modePaiement': 'especes'}, format='json'
        )

        self.assertEqual(reponse.status_code, 404)
        pret.refresh_from_db()
        self.assertEqual(pret.statut, 'approuve')
        self.assertFalse(HistoriqueOperation.objects.filter(gie=self.autre_gie, type_operation='sortie').exists())

    def test_remboursement_d_un_pret_d_un_autre_groupement_impossible(self):
        pret = Pret.objects.create(membre=self.membre_beta, montant=20000, statut='en_cours')

        reponse = self.client_de(self.tresorier).post(
            f'/api/prets/{pret.id}/rembourser/', {'modePaiement': 'especes'}, format='json'
        )

        self.assertEqual(reponse.status_code, 404)
        pret.refresh_from_db()
        self.assertEqual(pret.statut, 'en_cours')

    def test_liste_et_detail_limites_au_groupement(self):
        pret_alpha = Pret.objects.create(membre=self.membre, montant=10000)
        pret_beta = Pret.objects.create(membre=self.membre_beta, montant=20000)

        liste = self.client_de(self.membre).get('/api/prets/').json()
        identifiants = [p['id'] for p in (liste if isinstance(liste, list) else liste.get('results', []))]

        self.assertIn(pret_alpha.id, identifiants)
        self.assertNotIn(pret_beta.id, identifiants)
        self.assertEqual(self.client_de(self.membre).get(f'/api/prets/{pret_beta.id}/').status_code, 404)

    def test_identifiant_inexistant(self):
        self.assertEqual(
            self.client_de(self.president).post('/api/prets/999999/approuver/', {'dureeMois': 3}, format='json').status_code,
            404
        )


class CyclePretTestCase(PretsMixin, TestCase):

    def test_approbation_decaissement_remboursement_dans_son_groupement(self):
        pret = Pret.objects.create(membre=self.membre, montant=20000)

        reponse = self.client_de(self.president).post(
            f'/api/prets/{pret.id}/approuver/', {'dureeMois': 3}, format='json'
        )
        self.assertEqual(reponse.status_code, 200)
        pret.refresh_from_db()
        self.assertEqual(pret.statut, 'approuve')

        reponse = self.client_de(self.tresorier).post(
            f'/api/prets/{pret.id}/decaisser/', {'modePaiement': 'especes'}, format='json'
        )
        self.assertEqual(reponse.status_code, 200)
        pret.refresh_from_db()
        self.assertEqual(pret.statut, 'en_cours')
        self.assertTrue(HistoriqueOperation.objects.filter(gie=self.gie, type_operation='sortie', pret=pret).exists())

        reponse = self.client_de(self.tresorier).post(
            f'/api/prets/{pret.id}/rembourser/', {'modePaiement': 'especes'}, format='json'
        )
        self.assertEqual(reponse.status_code, 200)
        pret.refresh_from_db()
        self.assertEqual(pret.statut, 'rembourse')
        self.assertTrue(HistoriqueOperation.objects.filter(gie=self.gie, type_operation='entree', pret=pret).exists())

    def test_droits_par_role(self):
        pret = Pret.objects.create(membre=self.membre, montant=20000)

        # Seul le président approuve, seul le trésorier décaisse
        self.assertEqual(
            self.client_de(self.tresorier).post(f'/api/prets/{pret.id}/approuver/', {'dureeMois': 3}, format='json').status_code,
            403
        )
        Pret.objects.filter(pk=pret.pk).update(statut='approuve', duree_mois=3)
        self.assertEqual(
            self.client_de(self.president).post(f'/api/prets/{pret.id}/decaisser/', {'modePaiement': 'especes'}, format='json').status_code,
            403
        )


class ValidationReglesPretTestCase(PretsMixin, TestCase):

    def test_valeurs_invalides_refusees_en_modification(self):
        for champ, valeur in (
            ('montantMax', -5000), ('montantMax', 0),
            ('dureeMaxMois', 0), ('dureeMaxMois', 1000),
            ('nombrePretsSimultanes', 0),
        ):
            reponse = self.client_de(self.president).patch(
                '/api/prets/regles/', {champ: valeur}, format='json'
            )
            self.assertEqual(reponse.status_code, 400, f'{champ}={valeur}')

        regle = ReglePret.objects.get(gie=self.gie)
        self.assertEqual(regle.montant_max, 100000)
        self.assertEqual(regle.duree_max_mois, 6)
        self.assertEqual(regle.nombre_prets_simultanes, 1)

    def test_valeurs_limites_acceptees(self):
        reponse = self.client_de(self.president).patch(
            '/api/prets/regles/',
            {'montantMax': 1, 'dureeMaxMois': 120, 'nombrePretsSimultanes': 1},
            format='json'
        )

        self.assertEqual(reponse.status_code, 200)
        regle = ReglePret.objects.get(gie=self.gie)
        self.assertEqual(regle.duree_max_mois, 120)

    def test_creation_avec_valeurs_invalides_refusee(self):
        gie = GIE.objects.create(nom='Gamma', region='Dakar', type_gie='groupement', code='GAMMA', statut='actif')
        president = Utilisateur.objects.create_user(
            telephone='770000021', nom='Nom', prenom='Prenom', role='president', gie=gie, statut='actif'
        )

        reponse = self.client_de(president).post(
            '/api/prets/regles/',
            {'montantMax': -1, 'dureeMaxMois': 0, 'nombrePretsSimultanes': 0},
            format='json'
        )

        self.assertEqual(reponse.status_code, 400)
        self.assertEqual(
            set(reponse.json()), {'montantMax', 'dureeMaxMois', 'nombrePretsSimultanes'}
        )
        self.assertFalse(ReglePret.objects.filter(gie=gie).exists())


class DoubleDecaissementTestCase(PretsMixin, TestCase):
    """Un envoi PayDunya déjà lancé ne doit jamais être doublé."""

    def setUp(self):
        # Parcours PayDunya réel (en mode test, le décaissement est simulé)
        mode_live = patch('paiements.paydunya_service.PAYDUNYA_MODE', 'live')
        mode_live.start()
        self.addCleanup(mode_live.stop)
        self.pret = Pret.objects.create(
            membre=self.membre, montant=20000, statut='approuve', duree_mois=3,
            mode_paiement='wave', token_decaissement_paydunya='jeton-envoi-1'
        )

    def decaisser(self, mode='wave'):
        return self.client_de(self.tresorier).post(
            f'/api/prets/{self.pret.id}/decaisser/', {'modePaiement': mode}, format='json'
        )

    def verification(self, statut, montant=20000):
        return {'statut': statut, 'montant_confirme': montant, 'response_code': '', 'response_text': ''}

    def test_envoi_en_cours_refuse_tout_nouveau_decaissement(self):
        with patch('prets.views.verifier_decaissement', return_value=self.verification('pending')), \
             patch('prets.views.initier_decaissement') as initier:
            for mode in ('wave', 'orange_money', 'especes'):
                self.assertEqual(self.decaisser(mode).status_code, 409, mode)

        initier.assert_not_called()
        self.pret.refresh_from_db()
        self.assertEqual(self.pret.statut, 'approuve')
        self.assertFalse(HistoriqueOperation.objects.filter(pret=self.pret, type_operation='sortie').exists())

    def test_statut_injoignable_refuse(self):
        with patch('prets.views.verifier_decaissement', side_effect=PayDunyaNetworkError('hors ligne')), \
             patch('prets.views.initier_decaissement') as initier:
            self.assertEqual(self.decaisser().status_code, 409)
        initier.assert_not_called()

    def test_envoi_reussi_valide_le_pret_sans_nouvel_envoi(self):
        with patch('prets.views.verifier_decaissement', return_value=self.verification('success')), \
             patch('prets.views.initier_decaissement') as initier:
            reponse = self.decaisser()

        self.assertEqual(reponse.status_code, 409)
        initier.assert_not_called()
        self.pret.refresh_from_db()
        self.assertEqual(self.pret.statut, 'en_cours')
        self.assertEqual(
            HistoriqueOperation.objects.filter(pret=self.pret, type_operation='sortie').count(), 1
        )

    def test_envoi_echoue_permet_un_nouvel_essai(self):
        with patch('prets.views.verifier_decaissement', return_value=self.verification('failed')), \
             patch('prets.views.initier_decaissement', return_value={'disburse_token': 'jeton-envoi-2'}) as initier, \
             patch('prets.views.soumettre_decaissement', return_value={'status': 'pending'}):
            reponse = self.decaisser()

        self.assertEqual(reponse.status_code, 200)
        initier.assert_called_once()
        self.pret.refresh_from_db()
        self.assertEqual(self.pret.token_decaissement_paydunya, 'jeton-envoi-2')
        self.assertEqual(self.pret.statut, 'approuve')

    def test_sans_envoi_precedent_le_decaissement_especes_reste_inchange(self):
        Pret.objects.filter(pk=self.pret.pk).update(token_decaissement_paydunya=None)

        with patch('prets.views.verifier_decaissement') as verifier:
            reponse = self.decaisser('especes')

        self.assertEqual(reponse.status_code, 200)
        verifier.assert_not_called()
        self.pret.refresh_from_db()
        self.assertEqual(self.pret.statut, 'en_cours')


class DecaissementModeTestCase(PretsMixin, TestCase):
    """PayDunya n'accepte les décaissements qu'avec des clés LIVE : en mode test, ils sont simulés."""

    def setUp(self):
        self.pret = Pret.objects.create(membre=self.membre, montant=20000, statut='approuve', duree_mois=3)

    def decaisser(self, mode):
        return self.client_de(self.tresorier).post(
            f'/api/prets/{self.pret.id}/decaisser/', {'modePaiement': mode}, format='json'
        )

    def test_mode_test_simule_le_decaissement_sans_appeler_paydunya(self):
        for mode in ('wave', 'orange_money'):
            with self.subTest(mode=mode):
                Pret.objects.filter(pk=self.pret.pk).update(statut='approuve', mode_paiement=None, date_echeance=None)
                HistoriqueOperation.objects.filter(pret=self.pret).delete()
                with patch('paiements.paydunya_service.PAYDUNYA_MODE', 'test'), \
                     patch('prets.views.initier_decaissement') as initier, \
                     patch('prets.views.soumettre_decaissement') as soumettre:
                    reponse = self.decaisser(mode)

                self.assertEqual(reponse.status_code, 200)
                initier.assert_not_called()
                soumettre.assert_not_called()
                self.pret.refresh_from_db()
                self.assertEqual(self.pret.statut, 'en_cours')
                self.assertEqual(self.pret.mode_paiement, mode)
                self.assertIsNotNone(self.pret.date_echeance)
                sortie = HistoriqueOperation.objects.get(pret=self.pret, type_operation='sortie')
                self.assertEqual(int(sortie.montant), 20000)

    def test_mode_live_passe_par_paydunya(self):
        with patch('paiements.paydunya_service.PAYDUNYA_MODE', 'live'), \
             patch('prets.views.initier_decaissement', return_value={'disburse_token': 'jeton'}) as initier, \
             patch('prets.views.soumettre_decaissement', return_value={'status': 'pending'}):
            reponse = self.decaisser('wave')

        self.assertEqual(reponse.status_code, 200)
        initier.assert_called_once()
        self.assertEqual(initier.call_args.kwargs['telephone_beneficiaire'], '770000003')
        self.pret.refresh_from_db()
        self.assertEqual(self.pret.statut, 'approuve')
        self.assertFalse(HistoriqueOperation.objects.filter(pret=self.pret, type_operation='sortie').exists())

    def test_prefixe_221_retire_sans_toucher_au_reste_du_numero(self):
        membre = Utilisateur.objects.create_user(
            telephone='+221771234567', nom='Nom', prenom='Prenom', role='membre', gie=self.gie, statut='actif'
        )
        pret = Pret.objects.create(membre=membre, montant=20000, statut='approuve', duree_mois=3)
        with patch('paiements.paydunya_service.PAYDUNYA_MODE', 'live'), \
             patch('prets.views.initier_decaissement', return_value={'disburse_token': 'jeton'}) as initier, \
             patch('prets.views.soumettre_decaissement', return_value={'status': 'pending'}):
            self.client_de(self.tresorier).post(f'/api/prets/{pret.id}/decaisser/', {'modePaiement': 'wave'}, format='json')

        self.assertEqual(initier.call_args.kwargs['telephone_beneficiaire'], '771234567')


class ModesRemboursementTestCase(PretsMixin, TestCase):
    """Le trésorier rembourse toujours en espèces, y compris son propre prêt."""

    def rembourser(self, utilisateur, pret, mode):
        return self.client_de(utilisateur).post(
            f'/api/prets/{pret.id}/rembourser/', {'modePaiement': mode}, format='json'
        )

    def test_tresorier_rembourse_son_propre_pret_en_especes(self):
        pret = Pret.objects.create(membre=self.tresorier, montant=20000, statut='en_cours', duree_mois=3)

        for mode in ('wave', 'orange_money'):
            with self.subTest(mode=mode):
                self.assertEqual(self.rembourser(self.tresorier, pret, mode).status_code, 400)

        self.assertEqual(self.rembourser(self.tresorier, pret, 'especes').status_code, 200)
        pret.refresh_from_db()
        self.assertEqual(pret.statut, 'rembourse')

    def test_membre_rembourse_pour_lui_meme_en_ligne_uniquement(self):
        pret = Pret.objects.create(membre=self.membre, montant=20000, statut='en_cours', duree_mois=3)
        self.assertEqual(self.rembourser(self.membre, pret, 'especes').status_code, 400)


class UrlAnnulationPaiementTestCase(TestCase):

    def test_url_annulation_contient_type_et_id(self):
        with patch('paiements.paydunya_service._CANCEL_URL', 'http://localhost:4200/paiement/annule'):
            self.assertEqual(
                construire_url_annulation('cotisation', 5),
                'http://localhost:4200/paiement/annule?type=cotisation&id=5'
            )

    def test_sans_url_configuree_rien_n_est_envoye(self):
        with patch('paiements.paydunya_service._CANCEL_URL', ''):
            self.assertEqual(construire_url_annulation('pret', 3), '')


class OrigineRetourPaiementTestCase(TestCase):
    """Le retour PayDunya ramène sur le site d'où le paiement a été lancé (session conservée)."""

    RETOUR = 'https://exemple.ngrok-free.dev/paiement/retour'
    ANNULATION = 'https://exemple.ngrok-free.dev/paiement/annule'

    def setUp(self):
        for nom, valeur in (('_RETURN_URL', self.RETOUR), ('_CANCEL_URL', self.ANNULATION)):
            p = patch(f'paiements.paydunya_service.{nom}', valeur)
            p.start()
            self.addCleanup(p.stop)

    def requete(self, **entetes):
        from django.test import RequestFactory
        return RequestFactory().post('/', **entetes)

    def test_retour_sur_l_adresse_locale_utilisee(self):
        origine = origine_requete(self.requete(HTTP_ORIGIN='http://localhost:8080'))
        self.assertEqual(origine, 'http://localhost:8080')
        self.assertEqual(construire_url_retour('cotisation', 5, origine),
                         'http://localhost:8080/paiement/retour?type=cotisation&id=5')
        self.assertEqual(construire_url_annulation('cotisation', 5, origine),
                         'http://localhost:8080/paiement/annule?type=cotisation&id=5')

    def test_origine_lue_dans_le_referer_si_absente(self):
        requete = self.requete(HTTP_REFERER='http://localhost:8080/mon-espace/cotisations')
        self.assertEqual(origine_requete(requete), 'http://localhost:8080')

    def test_adresse_publique_configuree_acceptee(self):
        self.assertEqual(origine_requete(self.requete(HTTP_ORIGIN='https://exemple.ngrok-free.dev')),
                         'https://exemple.ngrok-free.dev')

    def test_site_inconnu_ignore(self):
        origine = origine_requete(self.requete(HTTP_ORIGIN='https://site-pirate.example'))
        self.assertEqual(origine, '')
        self.assertEqual(construire_url_retour('pret', 3, origine), f'{self.RETOUR}?type=pret&id=3')
