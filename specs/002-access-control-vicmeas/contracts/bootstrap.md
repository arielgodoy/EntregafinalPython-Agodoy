# Contract: Bootstrap inicial del sistema

## A. Inicialización normal

```text
python manage.py inicializar_sistema <username>
```

La interfaz de consola solicita datos de usuario solo cuando el usuario no existe.
Reutiliza una empresa base única, crea o reutiliza el catálogo de vistas de acceso,
selecciona vistas SYSTEM adicionales, excluye vistas APPLICATION y reporta vistas
ambiguas. El usuario existente debe ser superusuario y staff; de lo contrario la
operación se rechaza. Las contraseñas no se imprimen.

Cuando se ejecuta sobre un superuser/staff existente, reutiliza el usuario, `Empresa 00`
y las vistas existentes, y completa únicamente permisos VICMEAS faltantes. No solicita
password, no elimina ni degrada permisos y no duplica registros.

Ejemplo conceptual: si el usuario ya existe y se incorpora una nueva Vista SYSTEM
obligatoria, la siguiente ejecución reutiliza el catálogo y completa solo el permiso
faltante para esa vista.

## B. Dry-run

```text
python manage.py inicializar_sistema <username> --dry-run
```

No solicita credenciales ni escribe la base de datos. Devuelve un resumen con las
decisiones previstas, incluyendo vistas seleccionadas, excluidas y ambiguas.

## Errores y límites

- Empresa base duplicada: `BootstrapInconsistency` convertido a `CommandError`.
- Usuario existente no superusuario o sin staff: operación rechazada.
- Vistas sin namespace o ruta clasificable: reportadas como ambiguas y omitidas.
- `Notificaciones - Topbar` se incorpora como excepción SYSTEM explícita porque es una
	dependencia interna del shell/base, incluso si su ruta existente es nula o legacy.
- Las demás vistas ambiguas no se incorporan sin clasificación segura.
- No existe contrato REST para este flujo.