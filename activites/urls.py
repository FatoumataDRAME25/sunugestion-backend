from rest_framework.routers import DefaultRouter

from .views import ActiviteViewSet


router = DefaultRouter()

router.register(
    r'activites',
    ActiviteViewSet,
    basename='activite'
)

urlpatterns = router.urls