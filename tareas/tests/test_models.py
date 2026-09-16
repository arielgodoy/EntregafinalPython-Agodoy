"""Tests del modelo Tarea (T009).

Reglas verificadas (spec/clarifications):
- Crear con solo título queda en BORRADOR (FR-001/FR-005).
- Publicar sin responsable falla (FR-007).
- Publicar con responsable inactivo falla (Q1).
- Publicar con responsable activo fija estado y fecha_publicacion (FR-008).
- Edición post-publicación sin responsable válido falla (FR-008).
- Transición PUBLICADA→BORRADOR imposible (Q2).
- Prioridad acepta solo valores aprobados; default NORMAL.

Nota: la empresa no se valida como inmutable a nivel de modelo (regla descartada); el
aislamiento multiempresa se verifica en las vistas (test_views.py).
"""

from datetime import date

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import ProtectedError
from django.test import TestCase

from access_control.models import Empresa
from organizacion.models import Departamento, Local, OrganizationalSource
from tareas.models import Tarea


class TareaModelTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.empresa = Empresa.objects.create(codigo="01", descripcion="Empresa A")
        cls.creador = User.objects.create_user(username="creador", password="x")
        cls.responsable = User.objects.create_user(username="responsable", password="x")

    def _crear_borrador(self, **kwargs):
        datos = {
            "titulo": "Tarea de prueba",
            "empresa": self.empresa,
            "creada_por": self.creador,
            "fecha_tope": date.today(),
        }
        datos.update(kwargs)
        return Tarea.objects.create(**datos)

    def _borrador_sin_guardar(self, **kwargs):
        datos = {
            "titulo": "Tarea de prueba",
            "empresa": self.empresa,
            "creada_por": self.creador,
            "fecha_tope": date.today(),
        }
        datos.update(kwargs)
        return Tarea(**datos)

    def _crear_local(self, empresa=None):
        return Local.objects.create(
            empresa=empresa or self.empresa,
            codigo="LOC-001",
            nombre="Local de prueba",
            source=OrganizationalSource.LOCAL,
        )

    def _crear_departamento(self, empresa=None):
        return Departamento.objects.create(
            empresa=empresa or self.empresa,
            codigo="DEP-001",
            nombre="Departamento de prueba",
            source=OrganizationalSource.LOCAL,
        )

    def test_crear_solo_titulo_queda_borrador(self):
        tarea = self._crear_borrador()
        self.assertEqual(tarea.estado, Tarea.Estado.BORRADOR)
        self.assertIsNone(tarea.fecha_publicacion)
        self.assertIsNotNone(tarea.fecha_creacion)
        self.assertEqual(tarea.empresa, self.empresa)

    def test_prioridad_default_es_normal(self):
        tarea = self._crear_borrador()
        self.assertEqual(tarea.prioridad, Tarea.Prioridad.NORMAL)

    def test_prioridad_rechaza_valor_no_aprobado(self):
        tarea = self._crear_borrador(prioridad="MEDIA")
        with self.assertRaises(ValidationError):
            tarea.full_clean()

    def test_tarea_historica_sin_ambito_sigue_siendovalida(self):
        tarea = self._crear_borrador()

        tarea.full_clean()

        self.assertIsNone(tarea.tipo_ambito)
        self.assertIsNone(tarea.local_id)
        self.assertIsNone(tarea.departamento_id)

    def test_local_ambito_valido_en_la_misma_empresa(self):
        tarea = self._crear_borrador(
            tipo_ambito=Tarea.Ambito.LOCAL,
            local=self._crear_local(),
        )

        tarea.full_clean()

    def test_departamento_ambito_valido_en_la_misma_empresa(self):
        tarea = self._crear_borrador(
            tipo_ambito=Tarea.Ambito.DEPARTAMENTO,
            departamento=self._crear_departamento(),
        )

        tarea.full_clean()

    def test_ambito_local_requiere_local_y_excluye_departamento(self):
        departamento = self._crear_departamento()

        with self.assertRaises(ValidationError):
            self._borrador_sin_guardar(tipo_ambito=Tarea.Ambito.LOCAL).full_clean()
        with self.assertRaises(ValidationError):
            self._borrador_sin_guardar(
                tipo_ambito=Tarea.Ambito.LOCAL,
                departamento=departamento,
            ).full_clean()

    def test_ambito_departamento_requiere_departamento_y_excluye_local(self):
        local = self._crear_local()

        with self.assertRaises(ValidationError):
            self._borrador_sin_guardar(
                tipo_ambito=Tarea.Ambito.DEPARTAMENTO,
            ).full_clean()
        with self.assertRaises(ValidationError):
            self._borrador_sin_guardar(
                tipo_ambito=Tarea.Ambito.DEPARTAMENTO,
                local=local,
            ).full_clean()

    def test_ambito_no_permite_ambas_dimensiones(self):
        with self.assertRaises(ValidationError):
            self._borrador_sin_guardar(
                tipo_ambito=Tarea.Ambito.LOCAL,
                local=self._crear_local(),
                departamento=self._crear_departamento(),
            ).full_clean()

    def test_dimensiones_sin_tipo_ambito_son_invalidas(self):
        with self.assertRaises(ValidationError):
            self._borrador_sin_guardar(local=self._crear_local()).full_clean()
        with self.assertRaises(ValidationError):
            self._borrador_sin_guardar(
                departamento=self._crear_departamento(),
            ).full_clean()

    def test_tipo_ambito_vacio_sin_dimensiones_es_valido(self):
        tarea = self._crear_borrador(tipo_ambito="")

        tarea.full_clean()

    def test_local_de_otra_empresa_es_invalido(self):
        otra_empresa = Empresa.objects.create(codigo="02", descripcion="Empresa B")
        tarea = self._crear_borrador(
            tipo_ambito=Tarea.Ambito.LOCAL,
            local=self._crear_local(otra_empresa),
        )

        with self.assertRaises(ValidationError):
            tarea.full_clean()

    def test_departamento_de_otra_empresa_es_invalido(self):
        otra_empresa = Empresa.objects.create(codigo="02", descripcion="Empresa B")
        tarea = self._crear_borrador(
            tipo_ambito=Tarea.Ambito.DEPARTAMENTO,
            departamento=self._crear_departamento(otra_empresa),
        )

        with self.assertRaises(ValidationError):
            tarea.full_clean()

    def test_database_constraint_rejects_invalid_ambito(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                self._crear_borrador(
                    tipo_ambito=Tarea.Ambito.LOCAL,
                    departamento=self._crear_departamento(),
                )

    def test_local_and_departamento_use_protect(self):
        local = self._crear_local()
        departamento = self._crear_departamento()
        self._crear_borrador(tipo_ambito=Tarea.Ambito.LOCAL, local=local)
        self._crear_borrador(
            titulo="Tarea de departamento",
            tipo_ambito=Tarea.Ambito.DEPARTAMENTO,
            departamento=departamento,
        )

        with self.assertRaises(ProtectedError):
            local.delete()
        with self.assertRaises(ProtectedError):
            departamento.delete()

    def test_departamento_no_requiere_erp_ni_api(self):
        departamento = self._crear_departamento()
        tarea = self._crear_borrador(
            tipo_ambito=Tarea.Ambito.DEPARTAMENTO,
            departamento=departamento,
        )

        tarea.full_clean()

    def test_publicar_sin_responsable_falla(self):
        tarea = self._crear_borrador()
        with self.assertRaises(ValidationError):
            tarea.publicar()
        tarea.refresh_from_db()
        self.assertEqual(tarea.estado, Tarea.Estado.BORRADOR)

    def test_publicar_con_responsable_inactivo_falla(self):
        self.responsable.is_active = False
        self.responsable.save()
        tarea = self._crear_borrador(responsable=self.responsable)
        with self.assertRaises(ValidationError):
            tarea.publicar()
        tarea.refresh_from_db()
        self.assertEqual(tarea.estado, Tarea.Estado.BORRADOR)

    def test_publicar_con_responsable_activo_ok(self):
        tarea = self._crear_borrador(responsable=self.responsable)
        tarea.publicar()
        tarea.refresh_from_db()
        self.assertEqual(tarea.estado, Tarea.Estado.PUBLICADA)
        self.assertIsNotNone(tarea.fecha_publicacion)

    def test_publicada_sin_responsable_falla_validacion(self):
        tarea = self._crear_borrador(responsable=self.responsable)
        tarea.publicar()
        tarea.responsable = None
        with self.assertRaises(ValidationError):
            tarea.full_clean()

    def test_publicada_no_puede_volver_a_borrador(self):
        tarea = self._crear_borrador(responsable=self.responsable)
        tarea.publicar()
        tarea.refresh_from_db()
        tarea.estado = Tarea.Estado.BORRADOR
        with self.assertRaises(ValidationError):
            tarea.full_clean()

    def test_fecha_publicacion_inmutable(self):
        tarea = self._crear_borrador(responsable=self.responsable)
        tarea.publicar()
        tarea.refresh_from_db()
        tarea.fecha_publicacion = tarea.fecha_publicacion.replace(year=2000)
        with self.assertRaises(ValidationError):
            tarea.full_clean()

    def test_publicar_dos_veces_error_controlado(self):
        tarea = self._crear_borrador(responsable=self.responsable)
        tarea.publicar()
        tarea.refresh_from_db()
        fecha_original = tarea.fecha_publicacion
        with self.assertRaises(ValidationError):
            tarea.publicar()
        tarea.refresh_from_db()
        self.assertEqual(tarea.estado, Tarea.Estado.PUBLICADA)
        self.assertEqual(tarea.fecha_publicacion, fecha_original)
