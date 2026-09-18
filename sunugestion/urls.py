
from django.contrib import admin
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularRedocView, SpectacularSwaggerView

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/auth/', include('authentication.urls')),
    path('api/membres/', include('membres.urls')),
    path('api/cotisations/', include('cotisations.urls')),
    path('api/historiques/', include('historiques.urls')),
    
    # Endpoint de téléchargement du schéma JSON/YAML
    path('api/schema/', SpectacularAPIView.as_view(), name='schema'),
    
    # Interface Swagger UI :
    path('api/docs/', SpectacularSwaggerView.as_view(url_name='schema'), name='swagger-ui'),
    
    # Alternative (Redoc) :
    path('api/redoc/', SpectacularRedocView.as_view(url_name='schema'), name='redoc'),
]
