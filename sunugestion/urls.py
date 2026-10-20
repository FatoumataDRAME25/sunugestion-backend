
from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularRedocView, SpectacularSwaggerView

from extraction import views as extraction_views

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/auth/', include('authentication.urls')),
    path('api/membres/', include('membres.urls')),
    path('api/cotisations/', include('cotisations.urls')),
    path('api/historiques/', include('historiques.urls')),
    path('api/prets/', include('prets.urls')),
    path('api/activites/', include('activites.urls')),
    path('api/notifications/', include('notifications.urls')),
    path('api/paiements/', include('paiements.urls')),
    path('api/gie/', include('gie.urls')),
    path('api/diagnostic/', include('diagnostic.urls')),
    path('api/rapports/', include('rapports.urls')),
    path('api/abonnements/', include('abonnements.urls')),

    # OCR / extraction
    path('ocr/health', extraction_views.health, name='ocr-health'),
    path('api/process-document', extraction_views.process_document, name='process-document'),

    # Endpoint de téléchargement du schéma JSON/YAML
    path('api/schema/', SpectacularAPIView.as_view(), name='schema'),
    
    # Interface Swagger UI :
    path('api/docs/', SpectacularSwaggerView.as_view(url_name='schema'), name='swagger-ui'),
    
    # Alternative (Redoc) :
    path('api/redoc/', SpectacularRedocView.as_view(url_name='schema'), name='redoc'),
]

# Logos envoyés : servis par Django en développement uniquement ;
# en production (DEBUG=False), nginx les sert directement depuis le volume
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
