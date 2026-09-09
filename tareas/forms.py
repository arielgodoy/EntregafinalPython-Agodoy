"""Formularios de la app tareas."""

from django import forms

from access_control.services.permissions import get_valid_users_for_empresa

from .models import Avance, DocumentoTarea, Hito

from .models import Tarea


class HitoForm(forms.ModelForm):
    motivo = forms.CharField(required=False, strip=True)

    def __init__(self, *args, tarea=None, **kwargs):
        super().__init__(*args, **kwargs)
        if tarea is None:
            self.fields["responsable"].queryset = self.fields["responsable"].queryset.none()
        else:
            self.fields["responsable"].queryset = get_valid_users_for_empresa(tarea.empresa).filter(
                is_active=True
            )

    class Meta:
        model = Hito
        fields = ["nombre", "responsable", "cumplimiento", "peso"]


class HitoCumplimientoForm(forms.ModelForm):
    class Meta:
        model = Hito
        fields = ["cumplimiento"]


class HitoReasignacionForm(forms.Form):
    responsable = forms.ModelChoiceField(queryset=Hito._meta.get_field("responsable").remote_field.model.objects.none())
    motivo = forms.CharField(required=True, strip=True)

    def __init__(self, *args, tarea=None, **kwargs):
        super().__init__(*args, **kwargs)
        if tarea is not None:
            self.fields["responsable"].queryset = get_valid_users_for_empresa(tarea.empresa).filter(
                is_active=True
            )


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

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.estado != Tarea.Estado.BORRADOR:
            self.fields["fecha_tope"].disabled = True

    class Meta:
        model = Tarea
        fields = ["titulo", "descripcion", "prioridad", "responsable", "fecha_tope"]
        widgets = {
            "descripcion": forms.Textarea(attrs={"rows": 4}),
            "fecha_tope": forms.DateInput(attrs={"type": "date"}),
        }
