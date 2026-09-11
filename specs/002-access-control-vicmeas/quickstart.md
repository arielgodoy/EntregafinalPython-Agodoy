# Quickstart: Control de acceso VICMEAS

## Prerrequisitos

- Windows PowerShell.
- Entorno `.\venv_django5` disponible.
- Base de pruebas gestionada por Django.

## Validación focalizada

```powershell
.\venv_django5\Scripts\python.exe manage.py test access_control.tests.test_vicmeas_sidebar access_control.tests.test_permissions_mixin access_control.tests.test_access_utility --settings=AppDocs.settings_test
```

## Validación del sistema

```powershell
.\venv_django5\Scripts\python.exe manage.py check --settings=AppDocs.settings_test
```

## Escenarios mínimos

1. `V=True`, `I=False`: visible en sidebar, backend rechazado.
2. `V=False`, `I=True`: no visible, backend autorizado si la vista exige `I`.
3. Superusuario sin permisos: no recibe bypass.
4. Ocultamiento de una vista: solo cambia `V` de la empresa objetivo.
5. Asignación repetida: no duplica ni resetea banderas.

## Reejecución tras ampliar el catálogo

Si el catálogo bootstrap se amplía después de haber creado un usuario técnico, puede
ejecutarse nuevamente:

```powershell
.\venv_django5\Scripts\python.exe manage.py inicializar_sistema <username>
```

La ejecución reutiliza el usuario y completa únicamente los permisos faltantes; no
requiere recrear usuario ni cambiar su contraseña.