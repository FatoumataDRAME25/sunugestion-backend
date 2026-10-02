from django.urls import path

from .views import CotisationListView, CotisationPaiementView, SessionCotisationCreateView,  CotisationDetailView


urlpatterns = [
    path('sessions/',SessionCotisationCreateView.as_view(),name='session-cotisation-create'),
    path('sessions/<int:session_id>/cotisations/',CotisationListView.as_view(),name='cotisation-list'),
    path('<int:pk>/payer/',CotisationPaiementView.as_view(),name='cotisation-payer'),
    path('<int:pk>/', CotisationDetailView.as_view(), name='cotisation-detail'),
]
