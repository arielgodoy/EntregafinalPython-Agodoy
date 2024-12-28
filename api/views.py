from rest_framework import viewsets
from rest_framework.filters import SearchFilter
from rest_framework.permissions import IsAuthenticated
from .models import Contratopublicidad,LmovimientosDetalle19
from .serializers import ContratopublicidadSerializer,LmovimientosDetalle19Serializer
from django.conf import settings
class ContratopublicidadViewSet(viewsets.ModelViewSet):
    serializer_class = ContratopublicidadSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [SearchFilter]
    search_fields = ['nombre']

    def get_queryset(self):
        # Recupera la empresa desde la sesión o define un valor predeterminado
        cliente_sistema = settings.CONFIGURACIONES['CLIENTE_SISTEMA']
        empresa_codigo = self.request.session.get("empresa_codigo", "00")  # Por defecto "00"
        basedatos = f"{cliente_sistema}gestion{empresa_codigo}"
        print(basedatos)

        if not empresa_codigo:
            raise ValidationError("Empresa no configurada en la sesión.")

        # Filtra el queryset y especifica la base de datos con `using()`
        return Contratopublicidad.objects.using(basedatos).all()

class LmovimientosDetalle19ViewSet(viewsets.ModelViewSet):
    serializer_class = LmovimientosDetalle19Serializer
    permission_classes = [IsAuthenticated]
    filter_backends = [SearchFilter]
    search_fields = ['numero']

    def get_queryset(self):
        # Recupera la empresa desde la sesión o define un valor predeterminado
        cliente_sistema = settings.CONFIGURACIONES['CLIENTE_SISTEMA']
        empresa_codigo = self.request.session.get("empresa_codigo", "00")  # Por defecto "00"
        basedatos = f"{cliente_sistema}gestion{empresa_codigo}"
        print(basedatos)

        if not empresa_codigo:
            raise ValidationError("Empresa no configurada en la sesión.")

        # Filtra el queryset y especifica la base de datos con `using()`
        return LmovimientosDetalle19.objects.using(basedatos).all()    

