from django.urls import path

from .views import paydunya_callback

urlpatterns = [
    path('paydunya/callback/', paydunya_callback, name='paydunya-callback'),
]
