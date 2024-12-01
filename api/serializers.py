from rest_framework import serializers
from .models import Company,Persona, Ciudad,Propietario

#uso la misma validacion de la app biblioteca para agregar al serializer
from biblioteca.forms import PropietarioForm



class PropietarioSeralizer(serializers.ModelSerializer):
    class Meta:
        model = Propietario
        fields = ('__all__')

    def validate(self, data):
        # Crear una instancia del formulario de Propietario con los datos recibidos
        form = PropietarioForm(data=data)        
        # Validar los datos con las reglas definidas en el formulario
        if not form.is_valid():
            # Mapear los errores del formulario a los errores del serializador
            raise serializers.ValidationError(form.errors)        
        return data


class CiudadSerializer(serializers.ModelSerializer):
    class Meta:
        model = Ciudad
        fields = ['id', 'nombre']


from rest_framework import serializers
from .models import Persona, Ciudad

class PersonaSerializer(serializers.ModelSerializer):
    ciudad_id = serializers.IntegerField(source='ciudad.id')  # Campo para entrada y salida
    ciudad_nombre = serializers.CharField(source='ciudad.nombre')  # Campo para entrada y salida

    class Meta:
        model = Persona
        fields = ['id', 'nombre', 'edad', 'ciudad_id', 'ciudad_nombre']

    def update(self, instance, validated_data):
        # Manejar la ciudad
        ciudad_data = validated_data.pop('ciudad', None)  # Extraer datos relacionados con ciudad
        if ciudad_data:
            ciudad_id = ciudad_data.get('id')
            ciudad_nombre = ciudad_data.get('nombre')

            try:
                ciudad = Ciudad.objects.get(id=ciudad_id)
                # Si el nombre enviado es diferente al almacenado, actualizarlo
                if ciudad_nombre and ciudad.nombre != ciudad_nombre:
                    ciudad.nombre = ciudad_nombre
                    ciudad.save()
                # Asociar la ciudad actualizada con la instancia de Persona
                instance.ciudad = ciudad
            except Ciudad.DoesNotExist:
                raise serializers.ValidationError({'ciudad_id': f'No existe una ciudad con ID {ciudad_id}.'})

        # Actualizar los demás campos de Persona
        for attr, value in validated_data.items():
            setattr(instance, attr, value)

        # Guardar los cambios en la instancia de Persona
        instance.save()
        return instance



class CompanySerializer(serializers.ModelSerializer):
    class Meta:
        model = Company
        fields='__all__'
