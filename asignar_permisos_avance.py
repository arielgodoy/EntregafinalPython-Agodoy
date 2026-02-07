"""
Script para asignar permisos de modificar tarea a usuarios
Versión 2: Más exhaustiva - asigna a todos los usuarios en todas las empresas
"""
import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'AppDocs.settings')
django.setup()

from django.contrib.auth.models import User
from access_control.models import Vista, Permiso, Empresa

# Obtener vistas
vista_ver_detalle = Vista.objects.get(nombre='Ver Detalle Proyecto')
vista_mod_tarea = Vista.objects.get(nombre='Modificar Tarea')
print(f'✓ Vistas encontradas:')
print(f'  - {vista_ver_detalle.nombre}')
print(f'  - {vista_mod_tarea.nombre}\n')

# Estrategia 1: Usuarios con acceso a "Ver Detalle Proyecto"
print('📋 ESTRATEGIA 1: Usuarios con acceso a "Ver Detalle Proyecto"')
permisos_acceso = Permiso.objects.filter(
    vista=vista_ver_detalle,
    ingresar=True
).values_list('usuario_id', 'empresa_id').distinct()

count = 0
for user_id, empresa_id in permisos_acceso:
    user = User.objects.get(id=user_id)
    empresa = Empresa.objects.get(id=empresa_id)
    
    permiso, created = Permiso.objects.get_or_create(
        usuario=user,
        vista=vista_mod_tarea,
        empresa=empresa
    )
    permiso.modificar = True
    permiso.save()
    
    status = "creado" if created else "actualizado"
    print(f'  ✓ {user.username} (empresa {empresa.codigo}): {status}')
    count += 1

print(f'\n✅ {count} permisos asignados en Estrategia 1\n')

# Estrategia 2: Todos los usuarios activos en todas las empresas (fallback)
print('📋 ESTRATEGIA 2: Todos los usuarios activos en todas las empresas')
todos_usuarios = User.objects.filter(is_active=True)
todas_empresas = Empresa.objects.all()

count2 = 0
for user in todos_usuarios:
    for empresa in todas_empresas:
        permiso, created = Permiso.objects.get_or_create(
            usuario=user,
            vista=vista_mod_tarea,
            empresa=empresa
        )
        permiso.modificar = True
        permiso.save()
        
        if created:
            print(f'  ✓ {user.username} (empresa {empresa.codigo}): creado')
            count2 += 1

print(f'\n✅ {count2} nuevos permisos asignados en Estrategia 2')

# Resumen final
total_permisos = Permiso.objects.filter(
    vista=vista_mod_tarea,
    modificar=True
).count()

print(f'\n📊 TOTAL DE PERMISOS "Modificar Tarea":')
print(f'   {total_permisos} usuarios con permiso de modificar')
print(f'\n✅ Asignación completada')

