from rest_framework import viewsets
from rest_framework.filters import SearchFilter
from rest_framework.permissions import IsAuthenticated
from .models import Company,Persona,Propietario
from .serializers import CompanySerializer,PersonaSerializer,PropietarioSeralizer
class PropietarioViewSet(viewsets.ModelViewSet):
    queryset = Propietario.objects.all()
    serializer_class = PropietarioSeralizer
    filter_backends = [SearchFilter]
    search_fields = ['nombre']
    permission_classes = [IsAuthenticated]
    
class CompanyViewSet(viewsets.ModelViewSet):
    queryset = Company.objects.all()
    serializer_class = CompanySerializer
    permission_classes = [IsAuthenticated]
class PersonaViewSet(viewsets.ModelViewSet):
    queryset = Persona.objects.select_related('ciudad')  # Optimiza el join con select_related
    serializer_class = PersonaSerializer
    permission_classes = [IsAuthenticated]
    
