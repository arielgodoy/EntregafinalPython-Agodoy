from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticated
from .models import Company,Persona
from .serializers import CompanySerializer,PersonaSerializer



class CompanyViewSet(viewsets.ModelViewSet):
    queryset = Company.objects.all()
    serializer_class = CompanySerializer
    permission_classes = [IsAuthenticated]

class PersonaViewSet(viewsets.ModelViewSet):
    queryset = Persona.objects.select_related('ciudad')  # Optimiza el join con select_related
    serializer_class = PersonaSerializer
    permission_classes = [IsAuthenticated]
    