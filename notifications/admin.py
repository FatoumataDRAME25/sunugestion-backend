from django.contrib import admin
from notifications.models import Notification, NotificationUtilisateur

admin.site.register(Notification)
admin.site.register(NotificationUtilisateur)

