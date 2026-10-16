from django.urls import path

from .views import (
    NotificationLireView,
    NotificationListView,
    NotificationsToutLireView,
)

urlpatterns = [
    path('', NotificationListView.as_view(), name='notifications-liste'),
    path('tout-lire/', NotificationsToutLireView.as_view(), name='notifications-tout-lire'),
    path('<int:pk>/lire/', NotificationLireView.as_view(), name='notification-lire'),
]
