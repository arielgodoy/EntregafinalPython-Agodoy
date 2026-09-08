"""Shared test data helpers for the Phase 0 MVP baseline."""

from django.contrib.auth.models import User

from access_control.models import Empresa, Permiso, Vista
from tareas.models import Tarea


def create_empresa(codigo="01", descripcion="Empresa de prueba"):
    return Empresa.objects.create(codigo=codigo, descripcion=descripcion)


def create_user(username="usuario_prueba", password="password-prueba"):
    return User.objects.create_user(username=username, password=password)


def assign_permission(user, empresa, vista_nombre, **flags):
    vista = Vista.objects.get_or_create(nombre=vista_nombre)[0]
    defaults = {
        "ingresar": False,
        "crear": False,
        "modificar": False,
        "eliminar": False,
        "autorizar": False,
        "supervisor": False,
    }
    defaults.update(flags)
    return Permiso.objects.update_or_create(
        usuario=user,
        empresa=empresa,
        vista=vista,
        defaults=defaults,
    )[0]


def activate_company(client, empresa):
    session = client.session
    session["empresa_id"] = empresa.id
    session.save()


def create_tarea(empresa, creada_por, **kwargs):
    defaults = {
        "titulo": "Tarea de prueba",
        "empresa": empresa,
        "creada_por": creada_por,
    }
    defaults.update(kwargs)
    return Tarea.objects.create(**defaults)