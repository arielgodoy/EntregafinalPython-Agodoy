from dataclasses import dataclass
from datetime import timezone as datetime_timezone
from pathlib import Path

from django.core.files.storage import default_storage
from django.db import transaction
from django.db import models as django_models
from django.utils import timezone

from gestiondte.consultassql import (
    build_certificado_delete_query,
    build_certificado_insert_query,
    build_certificado_list_query,
    build_certificado_update_query,
)
from gestiondte.models import CertificadoSII
from gestiondte.services.connection_roles import get_gestiondte_connection
from gestiondte.utils.crypto import decrypt_password
from settings.models import SettingsMySQLConnection
from settings.services.mysql_connections import open_mysql_connection


def _normalize_mysql_datetime(value):
    if value is None or timezone.is_aware(value):
        return value
    return timezone.make_aware(value, timezone=datetime_timezone.utc)


@dataclass
class CertificateFile:
    name: str

    @property
    def path(self):
        return default_storage.path(self.name)

    @property
    def storage(self):
        return default_storage

    def __bool__(self):
        return bool(self.name)

    def delete(self, save=False):
        if self.name:
            default_storage.delete(self.name)


@dataclass
class CertificateRecord:
    id: int
    empresa_codigo: str
    archivo: CertificateFile
    password_encrypted: bytes | None = None
    activo: bool = False
    titular: str | None = None
    emisor_certificado: str | None = None
    numero_serie: str | None = None
    rut_titular: str | None = None
    valido_desde: object | None = None
    valido_hasta: object | None = None
    created_by_id: int | None = None
    updated_by_id: int | None = None
    created_by_username: str | None = None
    updated_by_username: str | None = None
    created_at: object | None = None
    updated_at: object | None = None

    @property
    def pk(self):
        return self.id

    def get_password(self):
        return decrypt_password(self.password_encrypted)

    @property
    def estado_vigencia(self):
        if not self.valido_hasta:
            return "Desconocido"
        ahora = timezone.now()
        delta = (self.valido_hasta - ahora).days
        if ahora > self.valido_hasta:
            return "Vencido"
        if delta <= 30:
            return "Por vencer"
        return "Vigente"

    def __str__(self):
        return f"Certificado {self.archivo.name} ({self.empresa_codigo})"


class CertificadoSIIRepository:
    role = "serverbasedte"

    def __init__(self):
        self.role_config = get_gestiondte_connection(self.role)

    @property
    def is_django(self):
        return self.role_config["type"] == "DJANGO"

    @property
    def django_alias(self):
        return self.role_config["alias"]

    def _mysql_connection(self):
        config = SettingsMySQLConnection.objects.get(
            pk=self.role_config["connection_id"]
        )
        database_name = self.role_config.get("database_name")
        if not database_name:
            raise ValueError("serverbasedte no tiene database_name configurado.")
        return open_mysql_connection(config, database_name=database_name)

    def list_by_empresa(self, empresa_codigo):
        if self.is_django:
            return list(
                CertificadoSII.objects.using(self.django_alias).filter(
                    empresa_codigo=empresa_codigo
                )
            )
        return self._fetch_mysql(build_certificado_list_query(empresa_codigo))

    def get_by_pk_and_empresa(self, pk, empresa_codigo):
        if self.is_django:
            return CertificadoSII.objects.using(self.django_alias).filter(
                pk=pk, empresa_codigo=empresa_codigo
            ).first()
        rows = self._fetch_mysql(build_certificado_list_query(empresa_codigo, pk=pk))
        return rows[0] if rows else None

    def create(self, instance, empresa_codigo, user):
        if instance.empresa_codigo != empresa_codigo:
            raise ValueError("El certificado no pertenece a la empresa activa.")
        if self.is_django:
            instance.created_by = user
            instance.created_by_username = user.username
            instance.updated_by = user
            instance.updated_by_username = user.username
            django_models.Model.save(instance, using=self.django_alias)
            if instance.activo:
                CertificadoSII.objects.using(self.django_alias).filter(
                    empresa_codigo=empresa_codigo
                ).exclude(pk=instance.pk).update(activo=False)
            return instance

        filename = instance.archivo.name
        storage_name = f"gestiondte/certificados/{empresa_codigo}/{Path(filename).name}"
        storage_name = default_storage.save(storage_name, instance.archivo.file)
        now = timezone.now()
        values = {
            "empresa_codigo": empresa_codigo,
            "archivo": storage_name,
            "password_encrypted": instance.password_encrypted,
            "activo": instance.activo,
            "titular": instance.titular,
            "emisor_certificado": instance.emisor_certificado,
            "numero_serie": instance.numero_serie,
            "rut_titular": instance.rut_titular,
            "valido_desde": _normalize_mysql_datetime(instance.valido_desde),
            "valido_hasta": _normalize_mysql_datetime(instance.valido_hasta),
            "created_by_id": user.id if user else None,
            "updated_by_id": user.id if user else None,
            "created_by_username": user.username if user else None,
            "updated_by_username": user.username if user else None,
            "created_at": now,
            "updated_at": now,
        }
        try:
            if instance.activo:
                cursor = None
                with self._mysql_connection() as connection:
                    cursor = connection.cursor()
                    cursor.execute(
                        "UPDATE gestiondte_certificadosii SET activo = 0 WHERE empresa_codigo = %s",
                        (empresa_codigo,),
                    )
                    connection.commit()
                    cursor.close()
            certificate_id = self._execute_insert(values)
        except Exception:
            default_storage.delete(storage_name)
            raise
        created = self.get_by_pk_and_empresa(certificate_id, empresa_codigo)
        if created is None:
            default_storage.delete(storage_name)
            raise RuntimeError("No se pudo recuperar el certificado creado.")
        return created

    def update_active(self, pk, empresa_codigo, user):
        if self.is_django:
            cert = self.get_by_pk_and_empresa(pk, empresa_codigo)
            if cert is None:
                return None
            cert.activo = not cert.activo
            cert.updated_by = user
            cert.updated_by_username = user.username
            django_models.Model.save(
                cert,
                using=self.django_alias,
                update_fields=["activo", "updated_by", "updated_by_username", "updated_at"],
            )
            if cert.activo:
                CertificadoSII.objects.using(self.django_alias).filter(
                    empresa_codigo=empresa_codigo
                ).exclude(pk=cert.pk).update(activo=False)
            return cert
        cert = self.get_by_pk_and_empresa(pk, empresa_codigo)
        if cert is None:
            return None
        active = not cert.activo
        values = {
            "activo": active,
            "updated_by_id": user.id,
            "updated_by_username": user.username,
            "updated_at": timezone.now(),
        }
        self._execute_update(pk, empresa_codigo, values)
        cert.activo = active
        cert.updated_by_id = user.id
        cert.updated_by_username = user.username
        return cert

    def delete(self, pk, empresa_codigo):
        cert = self.get_by_pk_and_empresa(pk, empresa_codigo)
        if cert is None:
            return None
        if self.is_django:
            with transaction.atomic(using=self.django_alias):
                django_models.Model.delete(cert, using=self.django_alias)
        else:
            self._execute_delete(pk, empresa_codigo)
        return cert

    def _fetch_mysql(self, query_and_params):
        query, params = query_and_params
        with self._mysql_connection() as connection:
            cursor = connection.cursor()
            try:
                cursor.execute(query, params)
                return [self._record_from_row(row) for row in cursor.fetchall()]
            finally:
                cursor.close()

    def _execute_insert(self, values):
        query, params = build_certificado_insert_query(values)
        with self._mysql_connection() as connection:
            cursor = connection.cursor()
            try:
                cursor.execute(query, params)
                connection.commit()
                return cursor.lastrowid
            except Exception:
                connection.rollback()
                raise
            finally:
                cursor.close()

    def _execute_update(self, pk, empresa_codigo, values):
        query, params = build_certificado_update_query(pk, empresa_codigo, values)
        with self._mysql_connection() as connection:
            cursor = connection.cursor()
            try:
                cursor.execute(query, params)
                connection.commit()
            except Exception:
                connection.rollback()
                raise
            finally:
                cursor.close()

    def _execute_delete(self, pk, empresa_codigo):
        query, params = build_certificado_delete_query(pk, empresa_codigo)
        with self._mysql_connection() as connection:
            cursor = connection.cursor()
            try:
                cursor.execute(query, params)
                connection.commit()
            except Exception:
                connection.rollback()
                raise
            finally:
                cursor.close()

    @staticmethod
    def _record_from_row(row):
        return CertificateRecord(
            id=row[0], empresa_codigo=row[1], archivo=CertificateFile(row[2]),
            password_encrypted=row[3], activo=bool(row[4]), titular=row[5],
            emisor_certificado=row[6], numero_serie=row[7], rut_titular=row[8],
            valido_desde=_normalize_mysql_datetime(row[9]),
            valido_hasta=_normalize_mysql_datetime(row[10]), created_by_id=row[11],
            updated_by_id=row[12], created_by_username=row[13],
            updated_by_username=row[14], created_at=_normalize_mysql_datetime(row[15]),
            updated_at=_normalize_mysql_datetime(row[16]),
        )
