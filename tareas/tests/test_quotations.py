from datetime import date
from decimal import Decimal

from django.apps import apps
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase

from proveedores.models import Proveedor
from tareas.models import Cotizacion, DocumentoCotizacion, RondaCotizacion
from tareas.services.quotations import (
    add_quotation_document,
    close_quotation_round,
    count_available_quotations,
    create_quotation,
    create_quotation_round,
    get_latest_quotation_round,
    open_next_quotation_round,
    quotation_minimum_met,
    update_quotation_status,
)
from tareas.tests.factories import create_empresa, create_tarea, create_user


class QuotationRoundTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.empresa = create_empresa(codigo="Q44")
        cls.usuario = create_user(username="quotations-user")
        cls.tarea = create_tarea(cls.empresa, cls.usuario)

    def test_first_round_starts_at_one_with_default_minimum(self):
        ronda = create_quotation_round(tarea=self.tarea)

        self.assertEqual(ronda.numero, 1)
        self.assertEqual(ronda.minimo_cotizaciones, 3)
        self.assertEqual(ronda.estado, RondaCotizacion.Estado.ABIERTA)
        self.assertIsNotNone(ronda.fecha_apertura)
        self.assertIsNone(ronda.fecha_cierre)

    def test_minimum_is_configurable_per_round(self):
        ronda = create_quotation_round(tarea=self.tarea, minimo_cotizaciones=5)

        self.assertEqual(ronda.minimo_cotizaciones, 5)

    def test_second_round_gets_next_number_and_preserves_first(self):
        primera = create_quotation_round(tarea=self.tarea, minimo_cotizaciones=2)
        segunda = create_quotation_round(tarea=self.tarea, minimo_cotizaciones=4)

        primera.refresh_from_db()
        self.assertEqual(segunda.numero, 2)
        self.assertEqual(primera.numero, 1)
        self.assertEqual(primera.minimo_cotizaciones, 2)
        self.assertEqual(segunda.minimo_cotizaciones, 4)
        self.assertEqual(RondaCotizacion.objects.filter(tarea=self.tarea).count(), 2)

    def test_each_task_has_its_own_first_round(self):
        otra_tarea = create_tarea(self.empresa, self.usuario, titulo="Otra tarea")

        primera = create_quotation_round(tarea=self.tarea)
        otra_primera = create_quotation_round(tarea=otra_tarea)

        self.assertEqual(primera.numero, 1)
        self.assertEqual(otra_primera.numero, 1)

    def test_duplicate_number_for_same_task_is_rejected(self):
        create_quotation_round(tarea=self.tarea)
        duplicate = RondaCotizacion(tarea=self.tarea, numero=1)

        with self.assertRaises(ValidationError):
            duplicate.full_clean()

    def test_minimum_and_number_must_be_positive(self):
        invalid_minimum = RondaCotizacion(tarea=self.tarea, numero=1, minimo_cotizaciones=0)
        invalid_number = RondaCotizacion(tarea=self.tarea, numero=0, minimo_cotizaciones=3)

        with self.assertRaises(ValidationError):
            invalid_minimum.full_clean()
        with self.assertRaises(ValidationError):
            invalid_number.full_clean()

    def test_round_belongs_to_task_and_derives_company_from_task(self):
        ronda = create_quotation_round(tarea=self.tarea)
        field_names = {field.name for field in RondaCotizacion._meta.fields}

        self.assertEqual(ronda.tarea, self.tarea)
        self.assertEqual(ronda.tarea.empresa, self.empresa)
        self.assertNotIn("empresa", field_names)
        self.assertFalse(any("proveedor" in name for name in field_names))

    def test_model_does_not_define_provider_or_quote_identity(self):
        field_names = {field.name for field in RondaCotizacion._meta.fields}

        self.assertNotIn("cotizacion", field_names)
        self.assertNotIn("proveedor_id", field_names)
        self.assertNotIn("rut_proveedor", field_names)


class QuotationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.empresa = create_empresa(codigo="Q45")
        cls.usuario = create_user(username="quotation-user")
        cls.proveedor = Proveedor.objects.create(nombre="Proveedor de prueba")
        cls.ronda = create_quotation_round(
            tarea=create_tarea(cls.empresa, cls.usuario),
        )

    def _create(self, **kwargs):
        defaults = {
            "ronda": self.ronda,
            "version": 1,
            "monto": Decimal("1250.50"),
            "fecha_cotizacion": date(2026, 9, 14),
            "proveedor": self.proveedor,
        }
        defaults.update(kwargs)
        return create_quotation(**defaults)

    def test_create_received_quotation_and_derive_task_company(self):
        cotizacion = self._create(observaciones="Oferta inicial")

        self.assertEqual(cotizacion.estado, Cotizacion.Estado.RECIBIDA)
        self.assertEqual(cotizacion.ronda, self.ronda)
        self.assertEqual(cotizacion.ronda.tarea.empresa, self.empresa)
        self.assertEqual(cotizacion.fecha_cotizacion, date(2026, 9, 14))
        self.assertEqual(cotizacion.observaciones, "Oferta inicial")

    def test_version_and_amount_must_be_valid(self):
        with self.assertRaises(ValidationError):
            self._create(version=0)
        with self.assertRaises(ValidationError):
            self._create(monto=Decimal("-0.01"))

    def test_all_contractual_states_are_supported_and_invalid_state_rejected(self):
        for version, estado in enumerate(Cotizacion.Estado, start=1):
            cotizacion = self._create(version=version, estado=estado)
            self.assertEqual(cotizacion.estado, estado)

        with self.assertRaises(ValidationError):
            self._create(estado="ADJUDICADA")

    def test_status_update_is_internal_and_does_not_select_provider(self):
        cotizacion = self._create()

        update_quotation_status(
            cotizacion=cotizacion,
            estado=Cotizacion.Estado.SELECCIONADA,
        )

        cotizacion.refresh_from_db()
        self.assertEqual(cotizacion.estado, Cotizacion.Estado.SELECCIONADA)
        self.assertTrue(cotizacion.vigente)

    def test_selected_quotation_exposes_local_provider_without_adjudication(self):
        cotizacion = self._create(estado=Cotizacion.Estado.SELECCIONADA)

        cotizacion.refresh_from_db()
        self.assertEqual(cotizacion.proveedor, self.proveedor)
        self.assertEqual(cotizacion.proveedor.nombre, "Proveedor de prueba")
        self.assertFalse(
            any(model.__name__ == "Adjudicacion" for model in apps.get_models())
        )

    def test_versions_are_independent_historical_rows(self):
        primera = self._create(version=1, vigente=False)
        segunda = self._create(version=2, vigente=True)

        primera.refresh_from_db()
        self.assertNotEqual(primera.pk, segunda.pk)
        self.assertEqual(primera.version, 1)
        self.assertFalse(primera.vigente)
        self.assertEqual(Cotizacion.objects.filter(ronda=self.ronda).count(), 2)

    def test_vigente_is_independent_from_selected_state(self):
        cotizacion = self._create(vigente=True, estado=Cotizacion.Estado.RECIBIDA)

        self.assertTrue(cotizacion.vigente)
        self.assertEqual(cotizacion.estado, Cotizacion.Estado.RECIBIDA)

    def test_document_with_file_preserves_user_and_validates_extension(self):
        cotizacion = self._create()
        documento = add_quotation_document(
            cotizacion=cotizacion,
            formato_archivo="PDF",
            usuario=self.usuario,
            archivo=SimpleUploadedFile("oferta.pdf", b"pdf"),
        )

        self.assertEqual(documento.usuario, self.usuario)
        self.assertEqual(documento.cotizacion, cotizacion)
        self.assertEqual(documento.formato_archivo, "PDF")

    def test_document_with_url_is_supported(self):
        documento = add_quotation_document(
            cotizacion=self._create(),
            formato_archivo="JPG",
            usuario=self.usuario,
            url="https://example.com/oferta.jpg",
        )

        self.assertEqual(documento.url, "https://example.com/oferta.jpg")

    def test_document_requires_exactly_one_source_and_matching_format(self):
        cotizacion = self._create()
        with self.assertRaises(ValidationError):
            add_quotation_document(
                cotizacion=cotizacion,
                formato_archivo="PDF",
                usuario=self.usuario,
            )
        with self.assertRaises(ValidationError):
            add_quotation_document(
                cotizacion=cotizacion,
                formato_archivo="PDF",
                usuario=self.usuario,
                archivo=SimpleUploadedFile("oferta.pdf", b"pdf"),
                url="https://example.com/oferta.pdf",
            )
        with self.assertRaises(ValidationError):
            add_quotation_document(
                cotizacion=cotizacion,
                formato_archivo="PDF",
                usuario=self.usuario,
                archivo=SimpleUploadedFile("oferta.jpg", b"jpg"),
            )

    def test_jpg_and_jpeg_formats_match_equivalent_extensions(self):
        cotizacion = self._create()
        jpg = add_quotation_document(
            cotizacion=cotizacion,
            formato_archivo="JPG",
            usuario=self.usuario,
            archivo=SimpleUploadedFile("oferta.jpg", b"jpg"),
        )
        jpeg = add_quotation_document(
            cotizacion=cotizacion,
            formato_archivo="JPEG",
            usuario=self.usuario,
            archivo=SimpleUploadedFile("oferta.jpeg", b"jpeg"),
        )

        self.assertEqual(jpg.cotizacion, jpeg.cotizacion)

    def test_models_do_not_define_provider_identity_or_duplicate_scope(self):
        quotation_fields = {field.name for field in Cotizacion._meta.fields}
        document_fields = {field.name for field in DocumentoCotizacion._meta.fields}

        self.assertNotIn("empresa", quotation_fields | document_fields)
        self.assertNotIn("tarea", quotation_fields | document_fields)
        self.assertIn("proveedor", quotation_fields)
        self.assertTrue(Cotizacion._meta.get_field("proveedor").null)
        self.assertIs(
            Cotizacion._meta.get_field("proveedor").remote_field.model,
            Proveedor,
        )
        self.assertFalse(any(name in quotation_fields | document_fields for name in {
            "proveedor_nombre",
            "rut",
            "razon_social",
        }))

    def test_quotation_can_have_provider_or_remain_pre_p2_null(self):
        provider = Proveedor.objects.create(nombre="Proveedor local")

        without_provider = Cotizacion.objects.create(
            ronda=self.ronda,
            version=20,
            monto=Decimal("1250.50"),
            fecha_cotizacion=date(2026, 9, 14),
        )
        with_provider = self._create(version=2, proveedor=provider)

        self.assertIsNone(without_provider.proveedor)
        self.assertEqual(with_provider.proveedor, provider)

    def test_multiple_quotations_can_share_active_or_inactive_provider(self):
        provider = Proveedor.objects.create(nombre="Proveedor historico")
        first = self._create(proveedor=provider)
        second = self._create(version=2, proveedor=provider)

        provider.activo = False
        provider.save(update_fields=["activo", "updated_at"])
        first.refresh_from_db()
        second.refresh_from_db()

        self.assertEqual(first.proveedor_id, provider.pk)
        self.assertEqual(second.proveedor_id, provider.pk)

    def test_create_quotation_remains_compatible_without_provider_and_persists_it_when_given(self):
        provider = Proveedor.objects.create(nombre="Proveedor opcional")
        with_provider = self._create(version=2, proveedor=provider)

        self.assertEqual(with_provider.proveedor_id, provider.pk)

    def test_create_quotation_requires_provider_and_does_not_insert_without_one(self):
        before = Cotizacion.objects.count()

        with self.assertRaisesMessage(ValidationError, "PROVIDER_REQUIRED"):
            create_quotation(
                ronda=self.ronda,
                version=20,
                monto=Decimal("1250.50"),
                fecha_cotizacion=date(2026, 9, 14),
            )

        self.assertEqual(Cotizacion.objects.count(), before)

    def test_create_quotation_rejects_non_provider_values(self):
        with self.assertRaisesMessage(ValidationError, "PROVIDER_INVALID"):
            create_quotation(
                ronda=self.ronda,
                version=20,
                monto=Decimal("1250.50"),
                fecha_cotizacion=date(2026, 9, 14),
                proveedor=self.proveedor.pk,
            )

    def test_provider_round_allows_versions_one_to_three_but_rejects_fourth(self):
        for version in (1, 2, 3):
            self._create(version=version)

        with self.assertRaisesMessage(ValidationError, "QUOTATION_VERSION_OUT_OF_RANGE"):
            self._create(version=4)

    def test_duplicate_provider_round_version_is_rejected(self):
        self._create(version=1)

        with self.assertRaisesMessage(ValidationError, "QUOTATION_VERSION_DUPLICATE"):
            self._create(version=1)

    def test_provider_and_round_scopes_are_independent(self):
        provider_b = Proveedor.objects.create(nombre="Proveedor B")
        for version in (1, 2, 3):
            self._create(version=version)
            self._create(version=version, proveedor=provider_b)

        otra_ronda = create_quotation_round(tarea=self.ronda.tarea)
        quotation = self._create_on_round(otra_ronda, version=1)

        self.assertEqual(quotation.ronda, otra_ronda)
        self.assertEqual(quotation.proveedor, self.proveedor)

    def test_version_limit_ignores_status_and_vigente(self):
        for version, estado, vigente in (
            (1, Cotizacion.Estado.RECIBIDA, False),
            (2, Cotizacion.Estado.SELECCIONADA, True),
            (3, Cotizacion.Estado.DESCARTADA, False),
        ):
            self._create(version=version, estado=estado, vigente=vigente)

        with self.assertRaisesMessage(ValidationError, "QUOTATION_VERSION_OUT_OF_RANGE"):
            self._create(version=4)

    def test_multiple_vigente_quotations_for_same_provider_count_as_one(self):
        provider = Proveedor.objects.create(nombre="Proveedor repetido")
        self._create(proveedor=provider)
        self._create(version=2, proveedor=provider)

        self.assertEqual(count_available_quotations(self.ronda), 1)

    def test_pre_p2_creation_does_not_create_provider_automatically(self):
        before = Proveedor.objects.count()
        quotation = Cotizacion.objects.create(
            ronda=self.ronda,
            version=20,
            monto=Decimal("1250.50"),
            fecha_cotizacion=date(2026, 9, 14),
        )

        self.assertIsNone(quotation.proveedor_id)
        self.assertEqual(Proveedor.objects.count(), before)

    def test_only_vigente_quotations_count_for_the_round_minimum(self):
        for index, vigente in enumerate((False, False, True, True, True, True), start=1):
            proveedor = Proveedor.objects.create(nombre=f"Proveedor conteo {index}")
            self._create(version=1, proveedor=proveedor, vigente=vigente)

        self.assertEqual(count_available_quotations(self.ronda), 4)
        self.assertTrue(quotation_minimum_met(self.ronda))

    def test_all_quotation_states_count_when_vigente(self):
        for index, estado in enumerate(Cotizacion.Estado, start=1):
            provider = Proveedor.objects.create(nombre=f"Proveedor estado {index}")
            self._create(version=1, proveedor=provider, estado=estado, vigente=True)

        self.assertEqual(count_available_quotations(self.ronda), 3)

    def test_minimum_three_fails_with_two_and_passes_with_three(self):
        self._create()
        self._create(version=2)
        self.assertFalse(quotation_minimum_met(self.ronda))

        provider_b = Proveedor.objects.create(nombre="Proveedor mínimo B")
        provider_c = Proveedor.objects.create(nombre="Proveedor mínimo C")
        self._create(version=1, proveedor=provider_b)
        self._create(version=1, proveedor=provider_c)
        self.assertTrue(quotation_minimum_met(self.ronda))

    def test_null_provider_and_inactive_provider_count_as_zero_and_one(self):
        null_quotation = Cotizacion.objects.create(
            ronda=self.ronda,
            version=20,
            monto=Decimal("10"),
            fecha_cotizacion=date(2026, 9, 14),
            vigente=True,
        )
        inactive_provider = Proveedor.objects.create(nombre="Proveedor inactivo")
        inactive_provider.activo = False
        inactive_provider.save(update_fields=["activo", "updated_at"])
        self._create(proveedor=inactive_provider, vigente=True)

        self.assertIsNone(null_quotation.proveedor_id)
        self.assertEqual(count_available_quotations(self.ronda), 1)

    def test_configurable_minimum_one_and_non_default_minimum(self):
        ronda = create_quotation_round(tarea=self.ronda.tarea, minimo_cotizaciones=1)
        self.assertFalse(quotation_minimum_met(ronda))
        create_quotation(
            ronda=ronda,
            version=1,
            monto=Decimal("10"),
            fecha_cotizacion=date(2026, 9, 14),
            proveedor=self.proveedor,
        )
        self.assertTrue(quotation_minimum_met(ronda))

    def test_round_close_requires_minimum_and_records_close_date(self):
        with self.assertRaisesMessage(ValidationError, "QUOTATION_MINIMUM_NOT_MET"):
            close_quotation_round(self.ronda)

        for version in (1, 2, 3):
            self._create(version=version)
        provider_b = Proveedor.objects.create(nombre="Proveedor cierre B")
        provider_c = Proveedor.objects.create(nombre="Proveedor cierre C")
        self._create(version=1, proveedor=provider_b)
        self._create(version=1, proveedor=provider_c)
        cerrada = close_quotation_round(self.ronda)

        self.assertEqual(cerrada.estado, RondaCotizacion.Estado.CERRADA)
        self.assertIsNotNone(cerrada.fecha_cierre)
        self.assertEqual(
            Cotizacion.objects.filter(ronda=self.ronda, estado=Cotizacion.Estado.RECIBIDA).count(),
            5,
        )

    def test_latest_round_controls_without_accumulating_previous_rounds(self):
        self._create()
        anterior = self.ronda
        siguiente = open_next_quotation_round(anterior)
        self._create_on_round(siguiente, version=1)

        self.assertEqual(get_latest_quotation_round(anterior.tarea), siguiente)
        self.assertFalse(quotation_minimum_met(siguiente))

    def _create_on_round(self, ronda, **kwargs):
        defaults = {
            "ronda": ronda,
            "version": kwargs.pop("version", 1),
            "monto": Decimal("1250.50"),
            "fecha_cotizacion": date(2026, 9, 14),
            "proveedor": self.proveedor,
        }
        defaults.update(kwargs)
        return create_quotation(**defaults)

    def test_open_next_round_inherits_minimum_and_preserves_history(self):
        self.ronda.minimo_cotizaciones = 5
        self.ronda.save(update_fields=["minimo_cotizaciones"])
        self._create()

        siguiente = open_next_quotation_round(self.ronda)

        self.assertEqual(siguiente.numero, self.ronda.numero + 1)
        self.assertEqual(siguiente.tarea, self.ronda.tarea)
        self.assertEqual(siguiente.minimo_cotizaciones, 5)
        self.assertEqual(siguiente.estado, RondaCotizacion.Estado.ABIERTA)
        self.assertEqual(siguiente.cotizaciones.count(), 0)
        self.ronda.refresh_from_db()
        self.assertEqual(self.ronda.cotizaciones.count(), 1)

    def test_get_latest_round_returns_none_when_task_has_no_rounds(self):
        tarea = create_tarea(self.empresa, self.usuario, titulo="Sin ronda")

        self.assertIsNone(get_latest_quotation_round(tarea))
