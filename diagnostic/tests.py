from unittest.mock import AsyncMock, patch

from django.core.cache import cache
from django.test import TestCase
from rest_framework.test import APIClient
from rest_framework.throttling import ScopedRateThrottle

from authentication.models import GIE, Utilisateur
from historiques.models import HistoriqueOperation

ANALYSE_OK = {'disponible': True, 'analyse': 'Trésorerie saine.'}
ANALYSE_KO = {'disponible': False, 'message': 'Service indisponible.'}


class DiagnosticMixin:

    @classmethod
    def setUpTestData(cls):
        cls.gie = GIE.objects.create(nom='Alpha', region='Dakar', type_gie='groupement', code='ALPHA', statut='actif')
        cls.president = Utilisateur.objects.create_user(
            telephone='770000001', nom='Nom', prenom='Prenom', role='president', gie=cls.gie, statut='actif'
        )

    def setUp(self):
        cache.clear()
        self.client = APIClient()
        self.client.force_authenticate(user=self.president)


class CacheAnalyseTestCase(DiagnosticMixin, TestCase):

    def test_analyse_reutilisee_tant_que_les_chiffres_ne_changent_pas(self):
        with patch('diagnostic.views.analyser_diagnostic', new=AsyncMock(return_value=ANALYSE_OK)) as ia:
            self.assertEqual(self.client.get('/api/diagnostic/').status_code, 200)
            self.assertEqual(self.client.get('/api/diagnostic/').status_code, 200)
            self.assertEqual(ia.await_count, 1)

            # Une nouvelle opération change les indicateurs : nouvelle analyse
            HistoriqueOperation.objects.create(gie=self.gie, type_operation='entree', montant=10000, libelle='Don')
            self.client.get('/api/diagnostic/')
            self.assertEqual(ia.await_count, 2)

    def test_analyse_indisponible_jamais_mise_en_cache(self):
        with patch('diagnostic.views.analyser_diagnostic', new=AsyncMock(return_value=ANALYSE_KO)) as ia:
            self.client.get('/api/diagnostic/')
            self.client.get('/api/diagnostic/')
            self.assertEqual(ia.await_count, 2)


class LimiteAssistantTestCase(DiagnosticMixin, TestCase):

    def test_questions_limitees_par_heure(self):
        reponse_ia = AsyncMock(return_value={'disponible': True, 'reponse': 'Bonjour.'})
        with patch('diagnostic.views.repondre_question', new=reponse_ia), \
             patch.dict(ScopedRateThrottle.THROTTLE_RATES, {'assistant': '2/hour'}):
            codes = [
                self.client.post('/api/diagnostic/assistant/', {'question': 'Solde ?'}, format='json').status_code
                for _ in range(3)
            ]

        self.assertEqual(codes, [200, 200, 429])
        self.assertEqual(reponse_ia.await_count, 2)
