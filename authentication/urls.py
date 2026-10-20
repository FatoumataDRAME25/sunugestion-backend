from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView
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
    VerifierOTPView,
    ProfilAdminView,
    ChangerPinAdminView,
    RenvoyerOTPView,
)

urlpatterns = [
    path('creer-gie/', CreerGIEView.as_view(), name='creer-gie'),
    path('inscription/', InscriptionPresidentView.as_view(), name='inscription'),
    path('verifier-otp/', VerifierOTPView.as_view(), name='verifier-otp'),
    path('renvoyer-otp/',RenvoyerOTPView.as_view(),name='renvoyer-otp'),
    path('connexion/', ConnexionView.as_view(), name='connexion'),
    path('liste-gies/', ListeGIEView.as_view(), name='liste-gies'),
    path('gies/statistiques/', StatistiquesGIEView.as_view(), name='statistiques-gies'),
    path('gies/evolution/', EvolutionGIEView.as_view(), name='evolution-gies'),
    path('gies/repartition-secteur/', RepartitionSecteursView.as_view(), name='repartition-secteurs'),
    path('gies/<int:pk>/', DetailGIEView.as_view(), name='detail-gie'),
    path('deconnexion/', DeconnexionView.as_view(), name='deconnexion'),
    path('refresh/', TokenRefreshView.as_view(), name='token_refresh'),
    path('profil/', ProfilAdminView.as_view(), name='profil-admin'),
    path('changer-pin/', ChangerPinAdminView.as_view(), name='changer-pin-admin'),
]
