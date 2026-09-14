from django.contrib import admin

from authentication.models import GIE, Utilisateur

# Register your models here.

admin.site.register(GIE),
admin.site.register(Utilisateur)