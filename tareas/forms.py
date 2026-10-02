"""Formularios de la app tareas."""

from os.path import splitext

from django.contrib.auth.models import User
from django import forms

from access_control.services.permissions import get_valid_users_for_empresa
from tareas.services.reading import COMMENT_PAGE_SIZE

from .models import (
    Avance,
    Comentario,
    DocumentoTarea,
    EvidenciaCierre,
    FormatoArchivo,
    Hito,
    MiniTarea,
    ReunionParticipante,
    ReunionRevision,
    ReunionTarea,
    Tarea,
    TareaParticipante,
)


class HitoForm(forms.ModelForm):
    class Meta:
        model = Hito
        fields = ["nombre", "cumplimiento", "peso"]


class HitoCrearForm(forms.ModelForm):
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


class CompletarHitoForm(forms.Form):
    resena_cierre = forms.CharField(required=True, strip=True, widget=forms.Textarea(attrs={"rows": 3}))
    formato_archivo = forms.ChoiceField(choices=FormatoArchivo.choices)
    archivo = forms.FileField(required=False)
    url = forms.URLField(required=False)

    def clean(self):
        cleaned_data = super().clean()
        tiene_archivo = bool(cleaned_data.get("archivo"))
        tiene_url = bool(cleaned_data.get("url"))
        if tiene_archivo == tiene_url:
            raise forms.ValidationError(
                "tareas.validation.evidence_file_or_url_required",
                code="tareas.validation.evidence_file_or_url_required",
            )
        return cleaned_data


class AvanceManualForm(forms.Form):
    porcentaje = forms.DecimalField(min_value=0, max_value=100, max_digits=5, decimal_places=2)


class AvancePonderadoForm(forms.Form):
    confirmar = forms.BooleanField(required=False, initial=True)


class DocumentoForm(forms.ModelForm):
    class Meta:
        model = DocumentoTarea
        fields = [
            "tipo",
            "formato_archivo",
            "archivo",
            "url",
            "fecha_documento",
            "fecha_vencimiento",
        ]
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
                "tareas.validation.document_file_or_url_required",
                code="tareas.validation.document_file_or_url_required",
            )
        return cleaned_data


class MultipleFileInput(forms.ClearableFileInput):
    allow_multiple_selected = True


class MultipleFileField(forms.FileField):
    widget = MultipleFileInput

    def clean(self, data, initial=None):
        if not data:
            return []
        files = data if isinstance(data, (list, tuple)) else [data]
        cleaned_files = []
        for file in files:
            cleaned_files.append(super().clean(file, initial))
        return cleaned_files


def _validate_comment_files(archivos, existing_count=0):
    archivos = list(archivos or [])
    if existing_count + len(archivos) > 5:
        raise forms.ValidationError(
            "tareas.messages.generic_error",
            code="tareas.messages.generic_error",
        )
    valid_extensions = {formato.lower() for formato, _label in FormatoArchivo.choices}
    for archivo in archivos:
        extension = splitext(archivo.name)[1].lower().lstrip(".")
        if extension not in valid_extensions:
            raise forms.ValidationError(
                "tareas.messages.generic_error",
                code="tareas.messages.generic_error",
            )
    return archivos


class ComentarioForm(forms.Form):
    contenido = forms.CharField(required=False, strip=False, widget=forms.Textarea)
    documentos = forms.ModelMultipleChoiceField(
        queryset=DocumentoTarea.objects.none(),
        required=False,
    )
    archivos = MultipleFileField(required=False)
    tipo_documento = forms.ChoiceField(
        choices=DocumentoTarea.Tipo.choices,
        required=False,
        initial=DocumentoTarea.Tipo.OTRO,
    )
    documentos_modificados = forms.BooleanField(required=False, widget=forms.HiddenInput)

    def __init__(self, *args, tarea=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.tarea = tarea
        if tarea is not None:
            self.fields["documentos"].queryset = DocumentoTarea.objects.filter(tarea=tarea)

    def clean(self):
        cleaned_data = super().clean()
        documentos = cleaned_data.get("documentos")
        archivos = cleaned_data.get("archivos") or []
        try:
            _validate_comment_files(
                archivos,
                existing_count=documentos.count() if documentos is not None else 0,
            )
        except forms.ValidationError as exc:
            self.add_error("archivos", exc)
        return cleaned_data

    def nuevos_documentos(self):
        tipo = self.cleaned_data.get("tipo_documento") or DocumentoTarea.Tipo.OTRO
        formatos_por_extension = {
            formato.lower(): formato for formato, _label in FormatoArchivo.choices
        }
        return [
            {
                "tipo": tipo,
                "formato_archivo": formatos_por_extension[
                    splitext(archivo.name)[1].lower().lstrip(".")
                ],
                "archivo": archivo,
            }
            for archivo in self.cleaned_data.get("archivos", [])
        ]


class ReconocerComentariosForm(forms.Form):
    comentario_ids = forms.CharField(required=True, strip=False)

    def __init__(self, *args, tarea=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.tarea = tarea

    def clean_comentario_ids(self):
        field_name = self.add_prefix("comentario_ids")
        if hasattr(self.data, "getlist"):
            raw_ids = self.data.getlist(field_name)
        else:
            raw_ids = [self.data.get(field_name, "")]
        values = [value.strip() for item in raw_ids for value in str(item).split(",")]
        try:
            comentario_ids = [int(value) for value in values]
        except (TypeError, ValueError) as exc:
            raise forms.ValidationError(
                "tareas.messages.generic_error",
                code="tareas.messages.generic_error",
            ) from exc
        if (
            not comentario_ids
            or len(comentario_ids) > COMMENT_PAGE_SIZE
            or len(comentario_ids) != len(set(comentario_ids))
        ):
            raise forms.ValidationError(
                "tareas.messages.generic_error",
                code="tareas.messages.generic_error",
            )
        encontrados = set(
            Comentario.objects.filter(
                tarea=self.tarea,
                pk__in=comentario_ids,
            ).values_list("pk", flat=True)
        )
        if encontrados != set(comentario_ids):
            raise forms.ValidationError(
                "tareas.messages.generic_error",
                code="tareas.messages.generic_error",
            )
        return comentario_ids


class MotivoComentarioForm(forms.Form):
    motivo = forms.CharField(required=True, strip=True)


class ParticipanteTareaForm(forms.Form):
    usuario = forms.ModelChoiceField(queryset=User.objects.none())

    def __init__(self, *args, empresa=None, active_only=True, **kwargs):
        super().__init__(*args, **kwargs)
        if empresa is not None:
            self.fields["usuario"].queryset = get_valid_users_for_empresa(
                empresa,
                active_only=active_only,
            )


class ParticipanteTareaAdminForm(ParticipanteTareaForm):
    rol = forms.ChoiceField(
        choices=(
            (TareaParticipante.Rol.PARTICIPANTE, "PARTICIPANTE"),
            (TareaParticipante.Rol.INVITADO_OBSERVADOR, "INVITADO_OBSERVADOR"),
        )
    )


class ResponsableTareaForm(forms.Form):
    responsable = forms.ModelChoiceField(
        queryset=User.objects.none(),
        required=False,
    )

    def __init__(self, *args, tarea=None, empresa=None, **kwargs):
        super().__init__(*args, **kwargs)
        if empresa is None and tarea is not None:
            empresa = tarea.empresa
        if empresa is not None:
            self.fields["responsable"].queryset = get_valid_users_for_empresa(
                empresa,
                active_only=True,
            )
        if tarea is not None:
            self.initial["responsable"] = tarea.responsable_id
            if tarea.estado != Tarea.Estado.BORRADOR:
                self.fields["responsable"].required = True


class MiniTareaCreateForm(forms.ModelForm):
    class Meta:
        model = MiniTarea
        fields = ["descripcion", "persona"]
        widgets = {
            "descripcion": forms.TextInput(attrs={"maxlength": 200}),
        }

    def __init__(self, *args, tarea=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["persona"].queryset = (
            get_valid_users_for_empresa(tarea.empresa, active_only=True)
            if tarea is not None
            else User.objects.none()
        )


class MiniTareaCloseForm(forms.Form):
    comentario = forms.CharField(required=True, strip=True, widget=forms.Textarea(attrs={"rows": 3}))
    archivos = MultipleFileField(required=False)
    destinatarios_notificacion = forms.ModelMultipleChoiceField(
        queryset=User.objects.none(), required=False
    )
    destinatarios_email = forms.ModelMultipleChoiceField(
        queryset=User.objects.none(), required=False
    )

    def __init__(self, *args, tarea=None, actor=None, **kwargs):
        super().__init__(*args, **kwargs)
        if tarea is None:
            return
        from tareas.services.participants import effective_participant_ids

        queryset = get_valid_users_for_empresa(tarea.empresa, active_only=True).filter(
            pk__in=effective_participant_ids(tarea)
        )
        if actor is not None:
            queryset = queryset.exclude(pk=actor.pk)
        self.fields["destinatarios_notificacion"].queryset = queryset
        self.fields["destinatarios_email"].queryset = queryset.exclude(email="")

    def clean_archivos(self):
        return _validate_comment_files(self.cleaned_data.get("archivos"))

    def nuevos_documentos(self):
        formatos_por_extension = {
            formato.lower(): formato for formato, _label in FormatoArchivo.choices
        }
        return [
            {
                "tipo": DocumentoTarea.Tipo.OTRO,
                "formato_archivo": formatos_por_extension[
                    splitext(archivo.name)[1].lower().lstrip(".")
                ],
                "archivo": archivo,
            }
            for archivo in self.cleaned_data.get("archivos", [])
        ]


class MiniTareaReopenForm(forms.Form):
    comentario = forms.CharField(required=True, strip=True, widget=forms.Textarea(attrs={"rows": 3}))


class EvidenciaConfigForm(forms.Form):
    requiere_evidencia_cierre = forms.BooleanField(required=False)


class EvidenciaRegistroForm(forms.Form):
    formato_archivo = forms.ChoiceField(choices=EvidenciaCierre._meta.get_field("formato_archivo").choices)
    archivo = forms.FileField(required=False)
    url = forms.URLField(required=False)

    def clean(self):
        cleaned_data = super().clean()
        tiene_archivo = bool(cleaned_data.get("archivo"))
        tiene_url = bool(cleaned_data.get("url"))
        if tiene_archivo == tiene_url:
            raise forms.ValidationError(
                "tareas.validation.evidence_file_or_url_required",
                code="tareas.validation.evidence_file_or_url_required",
            )
        return cleaned_data


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
        self.fields["fecha_tope"].required = True
        widget_classes = {
            "titulo": "form-control w-100",
            "descripcion": "form-control w-100",
            "prioridad": "form-select w-100",
            "responsable": "form-select w-100",
            "fecha_tope": "form-control w-100",
        }
        for field_name, class_names in widget_classes.items():
            widget = self.fields[field_name].widget
            existing_classes = widget.attrs.get("class", "")
            widget.attrs["class"] = " ".join(
                dict.fromkeys(f"{existing_classes} {class_names}".split())
            )
        if self.instance and self.instance.estado != Tarea.Estado.BORRADOR:
            self.fields["fecha_tope"].disabled = True

    class Meta:
        model = Tarea
        fields = ["titulo", "descripcion", "prioridad", "responsable", "fecha_tope"]
        widgets = {
            "descripcion": forms.Textarea(attrs={"rows": 4}),
            "fecha_tope": forms.DateInput(attrs={"type": "date"}),
        }


class ReunionRevisionForm(forms.ModelForm):
    class Meta:
        model = ReunionRevision
        fields = [
            "titulo",
            "descripcion",
            "fecha_hora_programada",
            "modalidad",
            "lugar_o_enlace",
            "tipo_ambito",
            "local",
            "departamento",
        ]
        widgets = {
            "fecha_hora_programada": forms.DateTimeInput(attrs={"type": "datetime-local"}),
            "descripcion": forms.Textarea(attrs={"rows": 4}),
        }


class ReunionParticipanteForm(forms.ModelForm):
    class Meta:
        model = ReunionParticipante
        fields = ["usuario"]

    def __init__(self, *args, empresa=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["usuario"].queryset = (
            get_valid_users_for_empresa(empresa, active_only=True)
            if empresa is not None
            else self.fields["usuario"].queryset.none()
        )


class ReunionTareaForm(forms.ModelForm):
    class Meta:
        model = ReunionTarea
        fields = ["tarea", "orden", "comentario_revision"]

    def __init__(self, *args, empresa=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["tarea"].queryset = (
            Tarea.objects.filter(empresa=empresa)
            if empresa is not None
            else self.fields["tarea"].queryset.none()
        )
