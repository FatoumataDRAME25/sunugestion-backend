from django.urls import path

from .views import (
    GrilleTarifaireView,
    InstanceAdminDetailView,
    InstancesAdminView,
    MonAbonnementView,
    PaiementAbonnementDetailView,
    PaiementManuelAdminView,
    PayerAbonnementView,
)

urlpatterns = [
    path('grille/', GrilleTarifaireView.as_view(), name='grille-tarifaire'),
    path('mon-abonnement/', MonAbonnementView.as_view(), name='mon-abonnement'),
    path('payer/', PayerAbonnementView.as_view(), name='payer-abonnement'),
    path('paiements/<int:pk>/', PaiementAbonnementDetailView.as_view(), name='paiement-abonnement'),
    path('admin/instances/', InstancesAdminView.as_view(), name='admin-instances'),
    path('admin/instances/<int:pk>/', InstanceAdminDetailView.as_view(), name='admin-instance'),
    path(
        'admin/instances/<int:pk>/paiement-manuel/',
        PaiementManuelAdminView.as_view(),
        name='admin-paiement-manuel'
    ),
]
