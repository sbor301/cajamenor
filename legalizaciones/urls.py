from rest_framework.routers import DefaultRouter

from .views import GastoViewSet, LegalizacionViewSet

router = DefaultRouter()
router.register(r"legalizaciones", LegalizacionViewSet, basename="legalizacion")
router.register(r"gastos", GastoViewSet, basename="gasto")

urlpatterns = router.urls
