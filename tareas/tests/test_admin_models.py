from types import SimpleNamespace

from django.apps import apps
from django.contrib import admin
from django.db import router
from django.test import RequestFactory, SimpleTestCase

from tareas.models import EnlaceTarea, MiniTareaEvento


class TareasAdminTests(SimpleTestCase):
    def setUp(self):
        self.request = RequestFactory().get('/admin/')
        self.request.user = SimpleNamespace(is_active=True, is_staff=True, is_superuser=True)

    def test_default_tareas_models_are_registered_read_only(self):
        models = [
            model
            for model in apps.get_app_config('tareas').get_models()
            if model._meta.managed
            and (router.db_for_write(model) or 'default') == 'default'
        ]

        for model in models:
            with self.subTest(model=model._meta.label):
                self.assertTrue(admin.site.is_registered(model))
                model_admin = admin.site._registry[model]
                self.assertFalse(model_admin.has_add_permission(self.request))
                self.assertFalse(model_admin.has_change_permission(self.request))
                self.assertFalse(model_admin.has_delete_permission(self.request))

    def test_lists_avoid_payload_fields_and_shared_link_token_hash_is_hidden(self):
        sensitive_fields = {
            'archivo',
            'comentario',
            'contenido',
            'descripcion',
            'destinatarios_email',
            'destinatarios_notificacion',
            'mini_tarea',
            'token_hash',
            'url',
        }
        for model in apps.get_app_config('tareas').get_models():
            with self.subTest(model=model._meta.label):
                model_admin = admin.site._registry[model]
                list_display = model_admin.get_list_display(self.request)
                self.assertLessEqual(len(list_display), 8)
                self.assertTrue(set(list_display).isdisjoint(sensitive_fields))

        enlace_admin = admin.site._registry[EnlaceTarea]
        self.assertIn('token_hash', enlace_admin.get_exclude(self.request))
        mini_tarea_event_admin = admin.site._registry[MiniTareaEvento]
        self.assertIn('mini_tarea', mini_tarea_event_admin.get_exclude(self.request))
