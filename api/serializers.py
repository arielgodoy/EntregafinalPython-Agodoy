from rest_framework import serializers
from .models import Contratopublicidad,LmovimientosDetalle19

class ContratopublicidadSerializer(serializers.ModelSerializer):
    class Meta:
        model = Contratopublicidad
        fields = '__all__'

LmovimientosDetalle19

class LmovimientosDetalle19Serializer(serializers.ModelSerializer):
    class Meta:
        model = LmovimientosDetalle19
        fields = '__all__'
