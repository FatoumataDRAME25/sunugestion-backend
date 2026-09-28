from django.urls import path

from .views import BadgesView, FCMTokenCreateView, MarquerModuleLuView

urlpatterns = [
    path('fcm-token/', FCMTokenCreateView.as_view(), name='fcm-token'),
    path('badges/', BadgesView.as_view(), name='badges'),
    path('badges/<str:module>/lire/', MarquerModuleLuView.as_view(), name='badges-lire'),
]
