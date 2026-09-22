from django.urls import path

from .views import PretApprobationView, PretDecaissementView, PretView, ReglePretView, PretRemboursementView


urlpatterns = [
    path('regles/', ReglePretView.as_view(), name='regles-pret'),
    path('', PretView.as_view(), name='demande-pret'),
    path('<int:pk>/approuver/',PretApprobationView.as_view(),name='approuver-pret'),
    path('<int:pk>/decaisser/', PretDecaissementView.as_view(), name='decaisser-pret'),
    path('<int:pk>/rembourser/',PretRemboursementView.as_view(),name='rembourser-pret'),
    path('<int:pk>/',PretView.as_view(),name='detail-pret'),
]