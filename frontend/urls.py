from django.urls import path
from . import views

urlpatterns = [
    path("", views.login_view, name="login"),
    path("login/", views.login_view),
    path("logout/", views.logout_view, name="logout"),
    path("dashboard/", views.dashboard, name="dashboard"),
    path("legalizaciones/", views.legalizacion_list, name="legalizacion_list"),
    path("legalizaciones/nueva/", views.legalizacion_create, name="legalizacion_create"),
    path("legalizaciones/<uuid:pk>/", views.legalizacion_detail, name="legalizacion_detail"),
    path("legalizaciones/<uuid:pk>/aprobar/", views.legalizacion_aprobar, name="legalizacion_aprobar"),
    path("legalizaciones/<uuid:pk>/rechazar/", views.legalizacion_rechazar, name="legalizacion_rechazar"),
    path("legalizaciones/<uuid:pk>/enviar/", views.legalizacion_enviar, name="legalizacion_enviar"),
    path("legalizaciones/<uuid:pk>/consignacion/", views.legalizacion_set_consignacion, name="legalizacion_set_consignacion"),
    path("legalizaciones/ocr/", views.ocr_factura, name="ocr_factura"),
    path("gastos/<int:pk>/rechazar/", views.gasto_rechazar, name="gasto_rechazar"),
    path("gastos/<int:pk>/restaurar/", views.gasto_restaurar, name="gasto_restaurar"),
]
