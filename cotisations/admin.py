from django.contrib import admin

from cotisations.models import Cotisation, SessionCotisation

# Register your models here.
admin.site.register(SessionCotisation)
admin.site.register(Cotisation)