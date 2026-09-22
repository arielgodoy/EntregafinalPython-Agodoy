from datetime import datetime, timedelta, timezone as datetime_timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, call, patch

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, SimpleTestCase, TestCase
from django.urls import reverse
from django.utils import timezone

from access_control.models import Empresa, Permiso, Vista
from gestiondte.models import CertificadoSII
from gestiondte.repositories.certificados import (
    CertificateFile,
    CertificateRecord,
    CertificadoSIIRepository,
)
from gestiondte.services.connection_roles import GestionDTERoleNotFoundError
from gestiondte.services.sii_auth import probar_autenticacion_sii
from gestiondte.tests.certificado_fixtures import configure_serverbasedte_django
from gestiondte.utils.crypto import encrypt_password


class CertificadoMultiempresaContractTests(TestCase):
    def setUp(self):
        configure_serverbasedte_django()
        self.user = User.objects.create_user(username="cert-contracts", password="pass")
        self.empresa_a = Empresa.objects.create(codigo="09", descripcion="Empresa A")
        self.empresa_b = Empresa.objects.create(codigo="10", descripcion="Empresa B")
        vista, _ = Vista.objects.get_or_create(
            nombre="Gestión DTE - Certificados PFX-DTE",
            defaults={"route_name": "gestion_dte:certificados"},
        )
        Permiso.objects.create(
            usuario=self.user,
            empresa=self.empresa_a,
            vista=vista,
            ingresar=True,
            crear=True,
            modificar=True,
            eliminar=True,
        )
        self.cert_b = CertificadoSII.objects.create(
            empresa_codigo=self.empresa_b.codigo,
            archivo="gestiondte/certificados/10/empresa-b.pfx",
            activo=True,
        )
        self.client = Client()
        self.client.login(username=self.user.username, password="pass")
        session = self.client.session
        session["empresa_id"] = self.empresa_a.id
        session.save()

    @patch("gestiondte.views.get_maestroempresa_by_codigo", return_value={"codigo": "09"})
    @patch("gestiondte.views.CertificadoSIIRepository.list_by_empresa")
    def test_mysql_record_pk_builds_listing_urls(self, list_by_empresa, _maestro):
        list_by_empresa.return_value = [
            CertificateRecord(
                id=27,
                empresa_codigo=self.empresa_a.codigo,
                archivo=CertificateFile("gestiondte/certificados/09/mysql.pfx"),
                activo=True,
                valido_hasta=timezone.now() + timedelta(days=365),
            )
        ]

        response = self.client.get(reverse("gestion_dte:certificados"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            reverse("gestion_dte:certificados_toggle_active", args=[27]),
        )
        self.assertContains(
            response,
            reverse("gestion_dte:certificados_probar_conexion", args=[27]),
        )
        self.assertContains(
            response,
            reverse("gestion_dte:certificados_eliminar", args=[27]),
        )

    def test_detail_rejects_certificate_company_b(self):
        response = self.client.get(
            reverse("gestion_dte:certificados_detail", args=[self.empresa_b.codigo])
        )

        self.assertEqual(response.status_code, 403)
        self.assertNotIn(b"empresa-b.pfx", response.content)

    def test_toggle_rejects_certificate_company_b_without_changing_it(self):
        response = self.client.post(
            reverse("gestion_dte:certificados_toggle_active", args=[self.cert_b.pk])
        )

        self.assertEqual(response.status_code, 403)
        self.cert_b.refresh_from_db()
        self.assertTrue(self.cert_b.activo)

    @patch("gestiondte.services.sii_auth.probar_autenticacion_sii")
    def test_probar_rejects_certificate_company_b_without_auth_call(self, probar):
        response = self.client.get(
            reverse("gestion_dte:certificados_probar_conexion", args=[self.cert_b.pk])
        )

        self.assertEqual(response.status_code, 403)
        probar.assert_not_called()

    @patch("gestiondte.views.CertificadoSIIRepository.create")
    @patch("cryptography.hazmat.primitives.serialization.pkcs12.load_key_and_certificates")
    def test_create_forces_session_company_over_manipulated_company(
        self, load_key_and_certificates, repository_create
    ):
        certificate = SimpleNamespace(
            subject=SimpleNamespace(
                rfc4514_string=lambda: "CN=Empresa A",
                get_attributes_for_oid=lambda _oid: [SimpleNamespace(value="Empresa A")],
            ),
            issuer=SimpleNamespace(rfc4514_string=lambda: "CN=Emisor"),
            serial_number=123,
            not_valid_before=None,
            not_valid_after=None,
        )
        load_key_and_certificates.return_value = (object(), certificate, [])
        uploaded = SimpleUploadedFile("empresa-a.pfx", b"pfx")
        repository_create.side_effect = lambda instance, _empresa, _user: instance

        with patch("gestiondte.views.CertificadoUploadForm") as form_class:
            form = form_class.return_value
            form.is_valid.return_value = True
            form.cleaned_data = {"password": ""}
            form.save.return_value = CertificadoSII(
                empresa_codigo=self.empresa_a.codigo,
                archivo=uploaded,
                activo=False,
            )
            response = self.client.post(
                reverse("gestion_dte:certificados_cargar"),
                {"empresa_codigo": self.empresa_b.codigo, "archivo": uploaded},
            )

        self.assertEqual(response.status_code, 302)
        submitted_data = form_class.call_args.args[0]
        self.assertEqual(submitted_data["empresa_codigo"], self.empresa_a.codigo)
        created_instance, company_code, _user = repository_create.call_args.args
        self.assertEqual(company_code, self.empresa_a.codigo)
        self.assertEqual(created_instance.empresa_codigo, self.empresa_a.codigo)
        self.assertNotEqual(created_instance.empresa_codigo, self.empresa_b.codigo)

    @patch("gestiondte.views.CertificadoSIIRepository")
    def test_delete_db_failure_does_not_delete_physical_file(self, repository_class):
        archive = Mock(name="archive")
        archive.name = "gestiondte/certificados/09/empresa-a.pfx"
        certificate = Mock(empresa_codigo=self.empresa_a.codigo, archivo=archive)
        repository = repository_class.return_value
        repository.get_by_pk_and_empresa.return_value = certificate
        repository.delete.side_effect = RuntimeError("delete failed")

        response = self.client.post(
            reverse("gestion_dte:certificados_eliminar", args=[self.cert_b.pk]),
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
            HTTP_ACCEPT="application/json",
        )

        self.assertEqual(response.status_code, 400)
        archive.delete.assert_not_called()

    def test_delete_success_removes_db_then_physical_file(self):
        archive = Mock(name="archive")
        archive.name = "gestiondte/certificados/09/empresa-a.pfx"
        certificate = Mock(empresa_codigo=self.empresa_a.codigo, archivo=archive)
        repository = Mock()
        repository.get_by_pk_and_empresa.return_value = certificate
        operations = Mock()
        operations.attach_mock(repository.delete, "db_delete")
        operations.attach_mock(archive.delete, "file_delete")

        with patch("gestiondte.views.CertificadoSIIRepository", return_value=repository), patch(
            "gestiondte.views.audit_log"
        ):
            response = self.client.post(
                reverse("gestion_dte:certificados_eliminar", args=[self.cert_b.pk]),
                HTTP_X_REQUESTED_WITH="XMLHttpRequest",
                HTTP_ACCEPT="application/json",
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            operations.mock_calls,
            [
                call.db_delete(self.cert_b.pk, self.empresa_a.codigo),
                call.file_delete(save=False),
            ],
        )


class CertificadoRepositoryDjangoContractTests(TestCase):
    def setUp(self):
        configure_serverbasedte_django()
        self.user = User.objects.create_user(username="repository-user", password="pass")
        self.repository = CertificadoSIIRepository()

    @patch("gestiondte.repositories.certificados.get_gestiondte_connection")
    def test_django_repository_operations_use_resolved_alias(self, get_connection):
        get_connection.return_value = {"type": "DJANGO", "alias": "default"}
        repository = CertificadoSIIRepository()
        first = CertificadoSII.objects.create(
            empresa_codigo="09", archivo="a.pfx", activo=False,
        )
        second = CertificadoSII.objects.create(
            empresa_codigo="09", archivo="b.pfx", activo=False,
        )
        delete_target = CertificadoSII.objects.create(
            empresa_codigo="09", archivo="delete.pfx", activo=False,
        )

        self.assertEqual(len(repository.list_by_empresa("09")), 3)
        self.assertEqual(repository.get_by_pk_and_empresa(first.pk, "09").pk, first.pk)
        delete_id = delete_target.pk
        deleted = repository.delete(delete_target.pk, "09")
        self.assertEqual(deleted.empresa_codigo, "09")
        self.assertFalse(CertificadoSII.objects.filter(pk=delete_id).exists())
        created = repository.create(
            CertificadoSII(empresa_codigo="09", archivo="created.pfx"), "09", self.user
        )
        self.assertEqual(created.empresa_codigo, "09")
        updated = repository.update_active(second.pk, "09", self.user)
        self.assertTrue(updated.activo)
        get_connection.assert_called_with("serverbasedte")

    @patch("gestiondte.repositories.certificados.CertificadoSII.objects")
    @patch(
        "gestiondte.repositories.certificados.get_gestiondte_connection",
        side_effect=GestionDTERoleNotFoundError("missing serverbasedte"),
    )
    def test_missing_serverbasedte_does_not_fallback_to_default(self, get_connection, objects):
        with self.assertRaises(GestionDTERoleNotFoundError):
            CertificadoSIIRepository()

        objects.assert_not_called()
        get_connection.assert_called_once_with("serverbasedte")


class CertificadoRepositoryMysqlContractTests(SimpleTestCase):
    def test_certificate_record_exposes_primary_key_alias(self):
        record = CertificateRecord(
            id=27,
            empresa_codigo="09",
            archivo=CertificateFile("certificado.pfx"),
        )

        self.assertEqual(record.id, 27)
        self.assertEqual(record.pk, 27)

    def test_get_password_uses_real_model_cipher_and_returns_plaintext(self):
        encrypted = encrypt_password("password-secreta")
        record = CertificateRecord(
            id=27,
            empresa_codigo="09",
            archivo=CertificateFile("certificado.pfx"),
            password_encrypted=encrypted,
        )

        self.assertEqual(record.get_password(), "password-secreta")
        self.assertEqual(record.password_encrypted, encrypted)

    def test_get_password_matches_orm_model_contract(self):
        encrypted = encrypt_password("password-secreta")
        orm_certificate = CertificadoSII(
            empresa_codigo="09",
            archivo="certificado.pfx",
            password_encrypted=encrypted,
        )
        mysql_record = CertificateRecord(
            id=27,
            empresa_codigo="09",
            archivo=CertificateFile("certificado.pfx"),
            password_encrypted=encrypted,
        )

        self.assertEqual(orm_certificate.get_password(), mysql_record.get_password())

    @patch("gestiondte.services.sii_auth.requests.post")
    @patch("gestiondte.services.sii_auth._build_jwt", return_value="h.p.s")
    @patch("gestiondte.utils.maestro.get_maestroempresa_by_codigo", return_value={"rutenviasii": "7762388-4"})
    @patch("gestiondte.services.sii_auth._extract_rut_from_cert", return_value="07762388-4")
    @patch("gestiondte.services.sii_auth.load_key_and_certificates")
    @patch("os.path.exists", return_value=True)
    @patch("builtins.open")
    def test_sii_auth_accepts_mysql_record_and_reads_password(
        self, open_file, path_exists, load_pfx, extract_rut, maestro, build_jwt, post
    ):
        response = MagicMock(status_code=200, headers={"Content-Type": "application/json"})
        response.json.return_value = {"access_token": "token"}
        post.return_value = response
        certificate = MagicMock()
        certificate.public_bytes.return_value = b"certificate-der"
        load_pfx.return_value = (MagicMock(), certificate, [])
        open_file.return_value.__enter__.return_value.read.return_value = b"pfx-data"
        record = CertificateRecord(
            id=27,
            empresa_codigo="09",
            archivo=CertificateFile("certificado.pfx"),
            password_encrypted=encrypt_password("password-secreta"),
            activo=True,
            valido_hasta=timezone.now() + timedelta(days=365),
        )

        result = probar_autenticacion_sii(record)

        self.assertTrue(result["success"])
        load_pfx.assert_called_once_with(b"pfx-data", b"password-secreta")

    @staticmethod
    def _row(pk=7, empresa="09", password=b"encrypted"):
        return (
            pk,
            empresa,
            "gestiondte/certificados/09/test.pfx",
            password,
            1,
            "Titular",
            "Emisor",
            "123",
            "12345678-9",
            None,
            None,
            1,
            1,
            "creator",
            "creator",
            None,
            None,
        )

    def test_mysql_naive_datetimes_are_utc_aware_and_state_is_safe(self):
        naive = datetime(2027, 8, 14, 12, 55, 55)
        record = CertificadoSIIRepository._record_from_row(
            self._row(password=b"encrypted")[:9]
            + (naive, naive, 1, 1, "creator", "creator", naive, naive)
        )

        self.assertTrue(timezone.is_aware(record.valido_desde))
        self.assertEqual(record.valido_hasta.tzinfo, datetime_timezone.utc)
        self.assertTrue(timezone.is_aware(record.created_at))
        self.assertTrue(timezone.is_aware(record.updated_at))
        self.assertEqual(record.estado_vigencia, "Vigente")

    def test_mysql_aware_datetimes_are_preserved_without_double_conversion(self):
        aware = datetime(2027, 8, 14, 12, 55, 55, tzinfo=datetime_timezone.utc)
        record = CertificadoSIIRepository._record_from_row(
            self._row()[:9] + (aware, aware, 1, 1, "creator", "creator", aware, aware)
        )

        self.assertIs(record.valido_hasta, aware)
        self.assertIs(record.created_at, aware)
        self.assertEqual(record.estado_vigencia, "Vigente")

    def test_mysql_none_datetimes_remain_none(self):
        record = CertificadoSIIRepository._record_from_row(self._row()[:9] + (None, None, 1, 1, "creator", "creator", None, None))

        self.assertIsNone(record.valido_desde)
        self.assertIsNone(record.valido_hasta)
        self.assertIsNone(record.created_at)
        self.assertIsNone(record.updated_at)
        self.assertEqual(record.estado_vigencia, "Desconocido")

    def test_django_and_mysql_naive_values_represent_the_same_instant(self):
        naive = datetime(2027, 8, 14, 12, 55, 55)
        aware = naive.replace(tzinfo=datetime_timezone.utc)
        django_record = CertificadoSII(empresa_codigo="09", archivo="django.pfx")
        django_record.valido_hasta = aware
        mysql_record = CertificadoSIIRepository._record_from_row(
            self._row()[:9] + (naive, naive, 1, 1, "creator", "creator", naive, naive)
        )

        self.assertEqual(django_record.valido_hasta, mysql_record.valido_hasta)
        self.assertEqual(django_record.valido_hasta.timestamp(), mysql_record.valido_hasta.timestamp())

    def _repository(self, connection_id=17, database_name="serverbasedte_db"):
        resolver = patch(
            "gestiondte.repositories.certificados.get_gestiondte_connection",
            return_value={
                "type": "MYSQL_CONFIG",
                "connection_id": connection_id,
                "database_name": database_name,
            },
        )
        resolver.start()
        self.addCleanup(resolver.stop)
        repository = CertificadoSIIRepository()
        config = MagicMock(name="mysql_config")
        config_patch = patch(
            "gestiondte.repositories.certificados.SettingsMySQLConnection.objects.get",
            return_value=config,
        )
        config_patch.start()
        self.addCleanup(config_patch.stop)
        return repository, config

    def _connection(self, cursors):
        connection = MagicMock(name="connection")
        connection.cursor.side_effect = cursors
        context = MagicMock(name="mysql_context")
        context.__enter__.return_value = connection
        context.__exit__.return_value = False
        return connection, context

    def test_list_and_get_use_serverbasedte_database_and_parameters(self):
        row = self._row()
        list_cursor = MagicMock()
        list_cursor.fetchall.return_value = [row]
        get_cursor = MagicMock()
        get_cursor.fetchall.return_value = [row]
        repository, config = self._repository()
        connection, context = self._connection([list_cursor, get_cursor])

        with patch(
            "gestiondte.repositories.certificados.open_mysql_connection",
            return_value=context,
        ) as open_connection:
            listed = repository.list_by_empresa("09")
            found = repository.get_by_pk_and_empresa(7, "09")

        self.assertEqual(listed[0].password_encrypted, b"encrypted")
        self.assertEqual(found.id, 7)
        self.assertIsInstance(found, CertificateRecord)
        open_connection.assert_called_with(config, database_name="serverbasedte_db")
        self.assertEqual(list_cursor.execute.call_args.args[1], ("09",))
        self.assertEqual(get_cursor.execute.call_args.args[1], (7, "09"))
        self.assertIn("FROM gestiondte_certificadosii", list_cursor.execute.call_args.args[0])
        self.assertIn("WHERE id = %s AND empresa_codigo = %s", get_cursor.execute.call_args.args[0])
        self.assertIs(connection, context.__enter__.return_value)

    def test_create_uses_database_password_bytes_and_recovers_inserted_record(self):
        insert_cursor = MagicMock()
        insert_cursor.lastrowid = 7
        select_cursor = MagicMock()
        select_cursor.fetchall.return_value = [self._row(password=b"raw-bytes")]
        repository, config = self._repository()
        connection, context = self._connection([insert_cursor, select_cursor])
        naive_valid_from = datetime(2027, 8, 14, 12, 55, 55)
        naive_valid_until = datetime(2027, 8, 15, 12, 55, 55)
        instance = CertificadoSII(
            empresa_codigo="09",
            archivo=SimpleUploadedFile("test.pfx", b"pfx"),
            password_encrypted=b"raw-bytes",
            activo=False,
            valido_desde=naive_valid_from,
            valido_hasta=naive_valid_until,
        )
        saved_name = "gestiondte/certificados/09/test.pfx"

        with patch(
            "gestiondte.repositories.certificados.open_mysql_connection",
            return_value=context,
        ) as open_connection, patch(
            "gestiondte.repositories.certificados.default_storage.save",
            return_value=saved_name,
        ) as storage_save, patch(
            "gestiondte.repositories.certificados.default_storage.delete",
        ) as storage_delete:
            created = repository.create(instance, "09", None)

        self.assertEqual(created.password_encrypted, b"raw-bytes")
        insert_params = insert_cursor.execute.call_args.args[1]
        self.assertIn(b"raw-bytes", insert_params)
        self.assertNotIn("raw-bytes", insert_params)
        self.assertTrue(timezone.is_aware(insert_params[8]))
        self.assertTrue(timezone.is_aware(insert_params[9]))
        self.assertEqual(insert_params[8].tzinfo, datetime_timezone.utc)
        self.assertEqual(insert_params[9].tzinfo, datetime_timezone.utc)
        storage_save.assert_called_once()
        storage_delete.assert_not_called()
        self.assertEqual(open_connection.call_args.kwargs["database_name"], "serverbasedte_db")
        self.assertIn("INSERT INTO gestiondte_certificadosii", insert_cursor.execute.call_args.args[0])
        self.assertEqual(select_cursor.execute.call_args.args[1], (7, "09"))
        self.assertEqual(connection.commit.call_count, 1)

    def test_create_insert_failure_deletes_only_new_saved_file_and_reraises(self):
        insert_cursor = MagicMock()
        insert_cursor.execute.side_effect = RuntimeError("insert failed")
        repository, _config = self._repository()
        _connection, context = self._connection([insert_cursor])
        instance = CertificadoSII(
            empresa_codigo="09",
            archivo=SimpleUploadedFile("new.pfx", b"pfx"),
            password_encrypted=b"encrypted",
        )
        saved_name = "gestiondte/certificados/09/new.pfx"

        with patch(
            "gestiondte.repositories.certificados.open_mysql_connection",
            return_value=context,
        ), patch(
            "gestiondte.repositories.certificados.default_storage.save",
            return_value=saved_name,
        ), patch(
            "gestiondte.repositories.certificados.default_storage.delete",
        ) as storage_delete:
            with self.assertRaises(RuntimeError):
                repository.create(instance, "09", None)

        storage_delete.assert_called_once_with(saved_name)
        insert_cursor.connection = None

    def test_update_active_and_delete_parameterize_pk_and_company(self):
        select_cursor = MagicMock()
        select_cursor.fetchall.return_value = [self._row(password=b"encrypted")]
        update_cursor = MagicMock()
        delete_select_cursor = MagicMock()
        delete_select_cursor.fetchall.return_value = [self._row(password=b"encrypted")]
        delete_cursor = MagicMock()
        repository, config = self._repository()
        connection, context = self._connection(
            [select_cursor, update_cursor, delete_select_cursor, delete_cursor]
        )
        user = MagicMock(id=5, username="editor")

        with patch(
            "gestiondte.repositories.certificados.open_mysql_connection",
            return_value=context,
        ) as open_connection:
            updated = repository.update_active(7, "09", user)
            deleted = repository.delete(7, "09")

        self.assertFalse(updated.activo)
        self.assertEqual(deleted.id, 7)
        self.assertEqual(update_cursor.execute.call_args.args[1][-2:], (7, "09"))
        self.assertTrue(timezone.is_aware(update_cursor.execute.call_args.args[1][3]))
        self.assertEqual(delete_cursor.execute.call_args.args[1], (7, "09"))
        self.assertIn("UPDATE gestiondte_certificadosii SET", update_cursor.execute.call_args.args[0])
        self.assertIn("DELETE FROM gestiondte_certificadosii", delete_cursor.execute.call_args.args[0])
        self.assertEqual(open_connection.call_args.kwargs["database_name"], "serverbasedte_db")

    def test_delete_sql_failure_propagates_without_storage_delete(self):
        select_cursor = MagicMock()
        select_cursor.fetchall.return_value = [self._row()]
        delete_cursor = MagicMock()
        delete_cursor.execute.side_effect = RuntimeError("delete failed")
        repository, _config = self._repository()
        _connection, context = self._connection([select_cursor, delete_cursor])

        with patch(
            "gestiondte.repositories.certificados.open_mysql_connection",
            return_value=context,
        ), patch(
            "gestiondte.repositories.certificados.default_storage.delete",
        ) as storage_delete:
            with self.assertRaises(RuntimeError):
                repository.delete(7, "09")

        storage_delete.assert_not_called()
