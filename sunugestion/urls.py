
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

    # OCR / extraction
    path('ocr/health', extraction_views.health, name='ocr-health'),
    path('api/ocr', extraction_views.ocr_only, name='ocr-only'),
    path('api/process-document', extraction_views.process_document, name='process-document'),

    # Endpoint de téléchargement du schéma JSON/YAML
    path('api/schema/', SpectacularAPIView.as_view(), name='schema'),
    
    # Interface Swagger UI :
    path('api/docs/', SpectacularSwaggerView.as_view(url_name='schema'), name='swagger-ui'),
    
    # Alternative (Redoc) :
    path('api/redoc/', SpectacularRedocView.as_view(url_name='schema'), name='redoc'),
]
