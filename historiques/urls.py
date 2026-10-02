from django.urls import path

from historiques.views import (
    HistoriqueOperationListView,
    HistoriqueOperationDetailView,
    OperationCreateView,
    SoldeView,
)

urlpatterns = [
    path('', HistoriqueOperationListView.as_view(), name='historique-list'),
    path('solde/', SoldeView.as_view(), name='solde'),
    path('operations/', OperationCreateView.as_view(), name='operation-create'),
    path('<int:pk>/', HistoriqueOperationDetailView.as_view(), name='historique-detail'),
]