# 📝 GUÍA RÁPIDA: Verificar Funcionamiento del Endpoint de Avance

## 🔍 Verificación Rápida

### 1. Verificar Permisos Asignados
```bash
python manage.py shell
```

```python
from access_control.models import Permiso, Vista, Empresa

# Contar permisos asignados
vista = Vista.objects.get(nombre='Modificar Tarea')
total = Permiso.objects.filter(vista=vista, modificar=True).count()
print(f'Total de usuarios con permiso "modificar": {total}')

# Verificar un usuario específico
from django.contrib.auth.models import User
user = User.objects.get(username='ariel')
empresa = Empresa.objects.get(codigo='01')
perm = Permiso.objects.filter(usuario=user, vista=vista, empresa=empresa).first()
print(f'ariel en empresa 01: {perm.modificar if perm else "NO EXISTE"}')
```

### 2. Ejecutar Script de Asignación
```bash
python asignar_permisos_avance.py
```

Output esperado:
```
✓ Vistas encontradas:
  - Ver Detalle Proyecto
  - Modificar Tarea

📋 ESTRATEGIA 1: Usuarios con acceso a "Ver Detalle Proyecto"
  ✓ [usuarios] actualizado

✅ X permisos asignados en Estrategia 1

📋 ESTRATEGIA 2: Todos los usuarios activos en todas las empresas
  ✓ [usuarios] creado

✅ Y nuevos permisos asignados en Estrategia 2

📊 TOTAL DE PERMISOS "Modificar Tarea":
   Z usuarios con permiso de modificar

✅ Asignación completada
```

### 3. Probar en Navegador

**Pasos:**
1. Login en Django con tu usuario
2. Ir a "Proyectos" → Seleccionar un proyecto
3. Expandir una tarea (que NO esté terminada)
4. Buscar el slider de avance
5. Mover el slider → Debería actualizar el % en tiempo real
6. Soltar el slider → Debería guardar y actualizar la barra visual

**Expectedado:**
- Slider se mueve suavemente
- % se actualiza al instante
- Barra de progreso se actualiza con el nuevo color
- Después de soltar, se mantiene el valor

### 4. Verificar en Console del Navegador

Abrir DevTools (F12) → Console → Mover slider

Deberías ver:
```javascript
// Sin errores
// POST /control-proyectos/tareas/3/avance/ → 200 OK
// Response: {success: true, porcentaje_avance: 50, ...}
```

### 5. Problemas Comunes

#### ❌ Slider no aparece
**Causa**: JavaScript no se cargó  
**Solución**: 
- Verificar que no hay errores en console (F12)
- Hacer reload de página (Ctrl+Shift+R)
- Verificar que tarea NO está en estado TERMINADA

#### ❌ Slider aparece pero no responde
**Causa**: Permisos no asignados  
**Solución**:
- Ejecutar: `python asignar_permisos_avance.py`
- Verificar en Django admin > Access Control > Permisos

#### ❌ Slider responde pero no guarda (403)
**Causa**: Sesión sin empresa correcta  
**Solución**:
- Logout y login nuevamente
- Cambiar empresa en selector (si existe)
- Limpiar cookies del navegador

#### ❌ Slider responde pero error 500
**Causa**: Error en servidor  
**Solución**:
- Ver logs de Django
- Ejecutar: `python manage.py check`
- Verificar que tarea existe en BD

---

## 📊 Información Técnica

### Endpoint
```
POST /control-proyectos/tareas/<id>/avance/
Content-Type: application/json

{
  "porcentaje_avance": 0-100
}
```

### Permisos Requeridos
- Vista: **Modificar Tarea**
- Permiso: **modificar**
- Empresa: Activa en sesión (session['empresa_id'])

### Status Codes
- **200**: Éxito ✓
- **400**: Validación falla (valor inválido, JSON, etc)
- **403**: Sin permisos O tarea de otra empresa
- **404**: Tarea no existe
- **405**: Método no es POST

### Validaciones
- ✓ Usuario autenticado
- ✓ Usuario tiene permiso "modificar" en "Modificar Tarea"
- ✓ Tarea existe
- ✓ Tarea pertenece a proyecto de empresa activa
- ✓ porcentaje_avance es número entre 0-100
- ✓ JSON válido

---

## 🆘 Si Todo Falla

1. **Verificar que ariel tiene permisos:**
   ```bash
   python manage.py shell
   from django.contrib.auth.models import User
   from access_control.models import Permiso, Vista, Empresa
   
   user = User.objects.get(username='ariel')
   vista = Vista.objects.get(nombre='Modificar Tarea')
   
   # Mostrar todos sus permisos en esta vista
   perms = Permiso.objects.filter(usuario=user, vista=vista)
   for p in perms:
       print(f'{p.usuario.username} - {p.empresa.codigo}: modificar={p.modificar}')
   ```

2. **Forzar asignación para un usuario:**
   ```bash
   python manage.py shell
   from django.contrib.auth.models import User
   from access_control.models import Permiso, Vista, Empresa
   
   user = User.objects.get(username='ariel')
   vista = Vista.objects.get(nombre='Modificar Tarea')
   empresa = Empresa.objects.all()
   
   for emp in empresa:
       perm, _ = Permiso.objects.get_or_create(usuario=user, vista=vista, empresa=emp)
       perm.modificar = True
       perm.save()
       print(f'✓ Asignado: {user.username} - {emp.codigo}')
   ```

3. **Ejecutar tests:**
   ```bash
   python test_completo_avance.py
   python test_ariel_empresa01.py
   ```

4. **Reiniciar servidor:**
   ```bash
   python manage.py runserver
   ```

---

**Última actualización**: 07 de febrero de 2026  
**Estado**: ✅ Funcionando correctamente
