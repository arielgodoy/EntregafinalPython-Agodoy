from django.urls import path
from auditoria.views import (
    AuditoriaBibliotecaListView,
    AuditoriaBibliotecaDetailView,
    AuditoriaGestionDTEListView,
    AuditoriaGestionDTEDetailView,
    AuditoriaBibliotecaLatestViewsView,
    AuditoriaGestionDTELatestViewsView,
    AuditoriaBibliotecaArchiveView,
    AuditoriaGestionDTEArchiveView,
    AuditoriaGestionDTEHistoricalDetailView,
)

app_name = "auditoria"

urlpatterns = [
    path("biblioteca/", AuditoriaBibliotecaListView.as_view(), name="auditoria_biblioteca_list"),
    path("biblioteca/<int:pk>/", AuditoriaBibliotecaDetailView.as_view(), name="auditoria_biblioteca_detail"),
    path("biblioteca/usuario/<int:user_id>/vistas/", AuditoriaBibliotecaLatestViewsView.as_view(), name="auditoria_biblioteca_latest_views"),
    path("gestiondte/", AuditoriaGestionDTEListView.as_view(), name="auditoria_gestiondte_list"),
    path("gestiondte/<int:pk>/", AuditoriaGestionDTEDetailView.as_view(), name="auditoria_gestiondte_detail"),
    path("gestiondte/historico/<int:pk>/", AuditoriaGestionDTEHistoricalDetailView.as_view(), name="auditoria_gestiondte_historical_detail"),
    path("gestiondte/usuario/<int:user_id>/vistas/", AuditoriaGestionDTELatestViewsView.as_view(), name="auditoria_gestiondte_latest_views"),
    path("biblioteca/archivo/", AuditoriaBibliotecaArchiveView.as_view(), name="auditoria_biblioteca_archive"),
    path("gestiondte/archivo/", AuditoriaGestionDTEArchiveView.as_view(), name="auditoria_gestiondte_archive"),
]
