from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView # <-- 1. AJOUTER CET IMPORT
from .views import (
    ConnexionView,
    CreerGIEView,
    DeconnexionView,
    DetailGIEView,
    EvolutionGIEView,
    InscriptionPresidentView,
    ListeGIEView,
    RepartitionSecteursView,
    StatistiquesGIEView,
    VerifierOTPView
)

urlpatterns = [
    path('creer-gie/', CreerGIEView.as_view(), name='creer-gie'),
    path('inscription/', InscriptionPresidentView.as_view(), name='inscription'),
    path('verifier-otp/', VerifierOTPView.as_view(), name='verifier-otp'),
    path('connexion/', ConnexionView.as_view(), name='connexion'),
    path('liste-gies/', ListeGIEView.as_view(), name='liste-gies'),
    path('gies/statistiques/', StatistiquesGIEView.as_view(), name='statistiques-gies'),
    path('gies/evolution/',EvolutionGIEView.as_view(),name='evolution-gies'),
    path('gies/repartition-secteur/', RepartitionSecteursView.as_view(), name='repartition-secteurs'),
    path('gies/<int:pk>/', DetailGIEView.as_view(), name='detail-gie'),
    path('deconnexion/', DeconnexionView.as_view(), name='deconnexion'),
    path('refresh/', TokenRefreshView.as_view(), name='token_refresh'), 
]
