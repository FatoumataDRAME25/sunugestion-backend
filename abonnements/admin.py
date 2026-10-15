from django.contrib import admin

from .models import Abonnement, PaiementAbonnement

admin.site.register(Abonnement)
admin.site.register(PaiementAbonnement)
