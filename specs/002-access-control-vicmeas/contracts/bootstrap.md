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
- No existe contrato REST para este flujo.