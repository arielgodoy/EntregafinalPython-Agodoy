Reglas del proyecto:
- Control de acceso: usar SIEMPRE access_control.decorators.verificar_permiso(vista_nombre, permiso_requerido).
- Permisos disponibles: ingresar, crear, modificar, eliminar, autorizar, supervisor.
- No inventar nuevos sistemas de permisos.
- Para nuevos módulos, copiar estructura y estilo de biblioteca.
- Si falta un helper, buscar primero en el repo antes de crear uno nuevo.
- Si no existe una pieza (ej. router DRF), reportarlo como NO ENCONTRADO y proponer la forma más consistente de agregarlo.
