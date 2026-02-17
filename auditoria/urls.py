from django.urls import path
from auditoria.views import AuditoriaBibliotecaListView, AuditoriaBibliotecaDetailView

app_name = "auditoria"

urlpatterns = [
    path("biblioteca/", AuditoriaBibliotecaListView.as_view(), name="auditoria_biblioteca_list"),
    path("biblioteca/<int:pk>/", AuditoriaBibliotecaDetailView.as_view(), name="auditoria_biblioteca_detail"),
]
