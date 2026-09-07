"""Formularios de la app tareas."""

from django import forms

from .models import Tarea


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
