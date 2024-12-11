from rest_framework import viewsets
from rest_framework.filters import SearchFilter
from rest_framework.permissions import IsAuthenticated
from .models import Company,Persona,Propietario
from .serializers import CompanySerializer,PersonaSerializer,PropietarioSeralizer
from django.conf import settings
class PropietarioViewSet(viewsets.ModelViewSet):
    serializer_class = PropietarioSeralizer
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
        return Propietario.objects.using(basedatos).all()

    
    
    
class CompanyViewSet(viewsets.ModelViewSet):
    queryset = Company.objects.using('eltit_gestion00').all()
    serializer_class = CompanySerializer
    permission_classes = [IsAuthenticated]
class PersonaViewSet(viewsets.ModelViewSet):
    queryset = Persona.objects.using('eltit_gestion00').select_related('ciudad')  # Optimiza el join con select_related
    serializer_class = PersonaSerializer
    permission_classes = [IsAuthenticated]
    
