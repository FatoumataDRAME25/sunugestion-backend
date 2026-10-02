from django.contrib import admin
from notifications.models import FCMToken, Notification, NotificationUtilisateur

admin.site.register(FCMToken)
admin.site.register(Notification)
admin.site.register(NotificationUtilisateur)

