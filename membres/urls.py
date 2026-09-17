from rest_framework.routers import DefaultRouter

from .views import MembreViewSet


router = DefaultRouter()

router.register( r'membres', MembreViewSet, basename='membre'
)

urlpatterns = router.urls