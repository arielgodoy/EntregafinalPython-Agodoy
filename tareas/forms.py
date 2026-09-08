"""Formularios de la app tareas."""

from django import forms

from .models import Avance, DocumentoTarea, Hito

from .models import Tarea


class HitoForm(forms.ModelForm):
    class Meta:
        model = Hito
        fields = ["nombre", "cumplimiento", "peso"]


class AvanceManualForm(forms.Form):
    porcentaje = forms.DecimalField(min_value=0, max_value=100, max_digits=5, decimal_places=2)


class AvancePonderadoForm(forms.Form):
    confirmar = forms.BooleanField(required=False, initial=True)


class DocumentoForm(forms.ModelForm):
    class Meta:
        model = DocumentoTarea
        fields = ["tipo", "archivo", "url", "fecha_documento", "fecha_vencimiento"]
        widgets = {
            "fecha_documento": forms.DateInput(attrs={"type": "date"}),
            "fecha_vencimiento": forms.DateInput(attrs={"type": "date"}),
        }

    def clean(self):
        cleaned_data = super().clean()
        tiene_archivo = bool(cleaned_data.get("archivo"))
        tiene_url = bool(cleaned_data.get("url"))
        if tiene_archivo == tiene_url:
            raise forms.ValidationError(
                "El documento debe indicar exactamente un archivo o una URL."
            )
        return cleaned_data


class EvidenciaConfigForm(forms.Form):
    requerida = forms.BooleanField(required=False)


class EvidenciaRegistroForm(forms.Form):
    documento = forms.ModelChoiceField(queryset=DocumentoTarea.objects.none())

    def __init__(self, *args, documentos=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["documento"].queryset = documentos or DocumentoTarea.objects.none()


class TareaForm(forms.ModelForm):
    """Formulario de creación/edición de tareas.

    Solo expone campos editables por el usuario (FR-001/FR-009). La empresa se
    asigna desde la sesión y el estado se gestiona por el flujo de publicación;
    ninguno es editable desde el formulario.

    La prioridad es opcional en la entrada (required=False): si el POST la omite,
    el modelo aplica su default NORMAL (initial informativo para el widget).
    """

    prioridad = forms.ChoiceField(
        choices=Tarea.Prioridad.choices,
        required=False,
        initial=Tarea.Prioridad.NORMAL,
    )

    class Meta:
        model = Tarea
        fields = ["titulo", "descripcion", "prioridad", "responsable"]
        widgets = {
            "descripcion": forms.Textarea(attrs={"rows": 4}),
        }
