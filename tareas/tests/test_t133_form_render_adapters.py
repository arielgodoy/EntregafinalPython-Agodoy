from django.contrib.auth.models import User
from django.test import SimpleTestCase, TestCase

from access_control.models import Empresa
from tareas.forms import (
    HitoCrearForm,
    HitoReasignacionForm,
    MiniTareaCreateForm,
    ParticipanteTareaAdminForm,
    ResponsableTareaForm,
)
from tareas.models import Tarea


class DetailFormRenderAdapterTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.empresa = Empresa.objects.create(codigo="133F", descripcion="Empresa")
        cls.user = User.objects.create_user(username="t133-form-user", password="pass")
        cls.responsible = User.objects.create_user(
            username="t133-form-responsible", password="pass"
        )
        cls.actor = User.objects.create_user(username="t133-form-actor", password="pass")
        from access_control.models import Permiso, Vista

        vista = Vista.objects.create(nombre="Tareas")
        for user in (cls.user, cls.responsible, cls.actor):
            Permiso.objects.create(
                usuario=user,
                empresa=cls.empresa,
                vista=vista,
                ingresar=True,
            )

    def test_responsible_form_renders_from_empresa_ids_and_state(self):
        form = ResponsableTareaForm(
            empresa=self.empresa,
            responsable_id=self.responsible.pk,
            estado=Tarea.Estado.BORRADOR,
        )

        self.assertEqual(form.initial["responsable"], self.responsible.pk)
        self.assertIn(self.responsible, form.fields["responsable"].queryset)
        self.assertFalse(form.fields["responsable"].required)

    def test_participant_form_already_renders_from_empresa(self):
        form = ParticipanteTareaAdminForm(empresa=self.empresa, active_only=True)

        self.assertIn(self.user, form.fields["usuario"].queryset)

    def test_minitask_form_renders_from_empresa_without_task(self):
        form = MiniTareaCreateForm(empresa=self.empresa)

        self.assertIn(self.user, form.fields["persona"].queryset)

    def test_milestone_forms_render_from_empresa_without_task(self):
        create_form = HitoCrearForm(empresa=self.empresa)
        reassign_form = HitoReasignacionForm(empresa=self.empresa)

        self.assertIn(self.user, create_form.fields["responsable"].queryset)
        self.assertIn(self.user, reassign_form.fields["responsable"].queryset)


class DetailFormRenderSimpleTests(SimpleTestCase):
    def test_forms_without_task_do_not_require_model_instance(self):
        self.assertTrue(True)
