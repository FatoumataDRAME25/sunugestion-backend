from django.urls import path

from .views import (
    BadgesView,
    MarquerModuleLuView,
    NotificationLireView,
    NotificationListView,
    NotificationsToutLireView,
)

urlpatterns = [
    path('', NotificationListView.as_view(), name='notifications-liste'),
    path('tout-lire/', NotificationsToutLireView.as_view(), name='notifications-tout-lire'),
    path('<int:pk>/lire/', NotificationLireView.as_view(), name='notification-lire'),
    path('badges/', BadgesView.as_view(), name='badges'),
    path('badges/<str:module>/lire/', MarquerModuleLuView.as_view(), name='badges-lire'),
]
