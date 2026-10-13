from django.urls import path

from rapports.views import RapportPeriodiqueView

urlpatterns = [
    path('periodique/', RapportPeriodiqueView.as_view(), name='rapport-periodique'),
]
