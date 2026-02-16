================= AI CONTEXT SYSTEM — DJANGO MULTIEMPRESA =================

Proyecto Django 5 multiempresa con control de acceso granular.

MODELO DE PERMISOS

Permisos definidos por combinación:

usuario + empresa + vista + flags

Flags disponibles:
I = Ingresar
c = Crear
m = Modificar
e = Eliminar
a = Autorizar
s = Supervisor

La empresa activa se define por session['empresa_id'].

Todos los accesos a datos deben respetar este scoping.

----------------------------------------------------------------------------

CONTROL DE ACCESO

Todas las vistas deben usar:

- VerificarPermisoMixin (class-based)
  o
- verificar_permiso (function-based)

La vista se identifica por Vista.nombre.

Permisos almacenados en modelo Permiso(usuario, empresa, vista).

----------------------------------------------------------------------------

SEGURIDAD MULTIEMPRESA

Está PROHIBIDO:

- Acceder datos de otra empresa
- Omitir empresa_id en consultas
- Exponer endpoints sin validación
- Usar request.user sin considerar empresa activa

----------------------------------------------------------------------------

I18N

Todos los textos visibles en HTML deben usar atributos data-key.
No introducir textos visibles hardcodeados.

----------------------------------------------------------------------------

PATRONES OBLIGATORIOS

- AJAX_DELETION_PATTERN.md
- Sistema Access Request tras 403
- Sistema de notificaciones centralizado
- Tests por app dentro de carpeta tests/

----------------------------------------------------------------------------

OBJETIVO DEL SISTEMA

Plataforma empresarial multiusuario, multiempresa y modular,
con enfoque en seguridad, trazabilidad y escalabilidad.

===========================================================================
