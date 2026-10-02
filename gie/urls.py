from django.urls import path
from .views import GieInfosView

urlpatterns = [
    path('infos/', GieInfosView.as_view(), name='gie-infos'),
]
