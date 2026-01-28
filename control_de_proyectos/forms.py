from django import forms
from .models import (
    Proyecto, Tarea, ClienteEmpresa, Profesional, 
    TipoTarea, DocumentoRequeridoTipoTarea, TareaDocumento
)


class ProyectoForm(forms.ModelForm):
    class Meta:
        model = Proyecto
        fields = [
            'nombre', 'descripcion', 'cliente', 'tipo_texto',
            'estado', 'profesionales', 'fecha_inicio_estimada', 'fecha_termino_estimada',
            'presupuesto', 'observaciones'
        ]
        widgets = {
            'nombre': forms.TextInput(attrs={'class': 'form-control'}),
            'descripcion': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'cliente': forms.Select(attrs={'class': 'form-select'}),
            'tipo_texto': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'ej: Consultoría, Diseño, Ejecución'}),
            'estado': forms.Select(attrs={'class': 'form-select'}),
            'profesionales': forms.CheckboxSelectMultiple(),
            'fecha_inicio_estimada': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}, format='%Y-%m-%d'),
            'fecha_termino_estimada': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}, format='%Y-%m-%d'),
            'presupuesto': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'observaciones': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
        }
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Asegurar que los campos de fecha tengan el formato correcto para el input type="date"
        if self.instance.pk:
            if self.instance.fecha_inicio_estimada:
                self.fields['fecha_inicio_estimada'].initial = self.instance.fecha_inicio_estimada
            if self.instance.fecha_termino_estimada:
                self.fields['fecha_termino_estimada'].initial = self.instance.fecha_termino_estimada


class TareaForm(forms.ModelForm):
    class Meta:
        model = Tarea
        fields = [
            'nombre', 'descripcion', 'proyecto', 'tipo_tarea', 'profesional_asignado',
            'estado', 'prioridad',
            'fecha_inicio_plan', 'fecha_fin_plan',
            'fecha_inicio_real', 'fecha_fin_real',
            'porcentaje_avance', 'horas_estimadas', 'horas_reales',
            'depende_de'
        ]
        widgets = {
            'nombre': forms.TextInput(attrs={'class': 'form-control'}),
            'descripcion': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'proyecto': forms.Select(attrs={'class': 'form-select'}),
            'tipo_tarea': forms.Select(attrs={'class': 'form-select'}),
            'profesional_asignado': forms.Select(attrs={'class': 'form-select'}),
            'estado': forms.Select(attrs={'class': 'form-select'}),
            'prioridad': forms.Select(attrs={'class': 'form-select'}),
            'fecha_inicio_plan': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}, format='%Y-%m-%d'),
            'fecha_fin_plan': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}, format='%Y-%m-%d'),
            'fecha_inicio_real': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}, format='%Y-%m-%d'),
            'fecha_fin_real': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}, format='%Y-%m-%d'),
            'porcentaje_avance': forms.NumberInput(attrs={'class': 'form-control', 'type': 'range', 'min': 0, 'max': 100}),
            'horas_estimadas': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.5'}),
            'horas_reales': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.5'}),
            'depende_de': forms.CheckboxSelectMultiple(),
        }
    
    def clean(self):
        cleaned_data = super().clean()
        estado = cleaned_data.get('estado')
        
        # Validar transiciones de estado
        if estado == 'TERMINADA':
            tarea = self.instance
            if not tarea.puede_marcar_terminada():
                self.add_error('estado', 'No puede marcar como Terminada si faltan documentos de salida obligatorios')
        
        return cleaned_data


class ClienteEmpresaForm(forms.ModelForm):
    class Meta:
        model = ClienteEmpresa
        fields = [
            'nombre', 'rut', 'email', 'telefono', 'direccion', 'ciudad',
            'contacto_nombre', 'contacto_telefono', 'activo'
        ]
        widgets = {
            'nombre': forms.TextInput(attrs={'class': 'form-control'}),
            'rut': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'XX.XXX.XXX-X'}),
            'email': forms.EmailInput(attrs={'class': 'form-control'}),
            'telefono': forms.TextInput(attrs={'class': 'form-control'}),
            'direccion': forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
            'ciudad': forms.TextInput(attrs={'class': 'form-control'}),
            'contacto_nombre': forms.TextInput(attrs={'class': 'form-control'}),
            'contacto_telefono': forms.TextInput(attrs={'class': 'form-control'}),
            'activo': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }


class ProfesionalForm(forms.ModelForm):
    class Meta:
        model = Profesional
        fields = ['nombre', 'rut', 'email', 'telefono', 'especialidad_texto', 'user', 'activo']
        widgets = {
            'nombre': forms.TextInput(attrs={'class': 'form-control'}),
            'rut': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'XX.XXX.XXX-X'}),
            'email': forms.EmailInput(attrs={'class': 'form-control'}),
            'telefono': forms.TextInput(attrs={'class': 'form-control'}),
            'especialidad_texto': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'ej: Ingeniero Civil'}),
            'user': forms.Select(attrs={'class': 'form-select'}),
            'activo': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }


class TipoTareaForm(forms.ModelForm):
    class Meta:
        model = TipoTarea
        fields = ['nombre', 'descripcion', 'activo']
        widgets = {
            'nombre': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'ej: Análisis, Diseño, Implementación'}),
            'descripcion': forms.Textarea(attrs={'class': 'form-control', 'rows': 3, 'placeholder': 'Descripción del tipo de tarea'}),
            'activo': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }


class DocumentoRequeridoTipoTareaForm(forms.ModelForm):
    class Meta:
        model = DocumentoRequeridoTipoTarea
        fields = ['tipo_tarea', 'nombre_documento', 'descripcion', 'es_obligatorio', 'categoria', 'tipo_doc', 'orden']
        widgets = {
            'tipo_tarea': forms.Select(attrs={'class': 'form-select'}),
            'nombre_documento': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'ej: Especificaciones técnicas'}),
            'descripcion': forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
            'es_obligatorio': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'categoria': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'ej: Técnico, Legal'}),
            'tipo_doc': forms.Select(attrs={'class': 'form-select'}),
            'orden': forms.NumberInput(attrs={'class': 'form-control', 'type': 'number', 'min': 1}),
        }


class TareaDocumentoForm(forms.ModelForm):
    """Formulario para cargar documentos a una tarea"""
    class Meta:
        model = TareaDocumento
        fields = ['nombre_documento', 'tipo_doc', 'archivo', 'url_documento', 'observaciones']
        widgets = {
            'nombre_documento': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Nombre del documento',
                'required': True
            }),
            'tipo_doc': forms.Select(attrs={
                'class': 'form-select',
                'required': True
            }),
            'archivo': forms.FileInput(attrs={
                'class': 'form-control',
                'accept': '.pdf,.doc,.docx,.xlsx,.xls,.jpg,.jpeg,.png,.gif,.zip,.rar'
            }),
            'url_documento': forms.URLInput(attrs={
                'class': 'form-control',
                'placeholder': 'O proporcione una URL del documento'
            }),
            'observaciones': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 2,
                'placeholder': 'Observaciones adicionales'
            }),
        }
    
    def clean(self):
        cleaned_data = super().clean()
        archivo = cleaned_data.get('archivo')
        url_documento = cleaned_data.get('url_documento')
        
        # Validar que al menos uno de los dos se proporcione
        if not archivo and not url_documento:
            raise forms.ValidationError('Debe proporcionar un archivo o una URL del documento')
        
        return cleaned_data
