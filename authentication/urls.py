from django.urls import path
from .views import (
    ConnexionView,
    CreerGIEView,
    DeconnexionView,
    InscriptionPresidentView,
    VerifierOTPView
)

urlpatterns = [
    path('creer-gie/', CreerGIEView.as_view(), name='creer-gie'),
    path('inscription/', InscriptionPresidentView.as_view(), name='inscription'),
    path('verifier-otp/', VerifierOTPView.as_view(), name='verifier-otp'),
    path('connexion/', ConnexionView.as_view(), name='connexion'),
    path('deconnexion/', DeconnexionView.as_view(), name='deconnexion'),
]