#!/usr/bin/env python
"""
Script de prueba: Verificar segregación de tareas por proyecto
Ejecutar con: python manage.py shell < test_segregacion_tareas.py
"""

from control_de_proyectos.models import Proyecto, Tarea, Profesional, ClienteEmpresa
from control_de_proyectos.forms import TareaForm
from access_control.models import Empresa
from django.contrib.auth.models import User

print("\n" + "="*80)
print("TEST: Segregación de datos en Crear Tarea")
print("="*80)

# 1. Obtener o crear empresas
try:
    empresa_a = Empresa.objects.filter(nombre__icontains="Empresa A").first() or Empresa.objects.first()
    empresa_b = Empresa.objects.all()[1] if Empresa.objects.count() > 1 else Empresa.objects.first()
    print(f"\n✅ Empresa A: {empresa_a.nombre} (ID: {empresa_a.id})")
    print(f"✅ Empresa B: {empresa_b.nombre} (ID: {empresa_b.id})")
except Exception as e:
    print(f"❌ Error obteniendo empresas: {e}")
    exit(1)

# 2. Obtener o crear cliente
try:
    cliente = ClienteEmpresa.objects.first()
    if not cliente:
        cliente = ClienteEmpresa.objects.create(
            nombre="Cliente Test",
            rut="12.345.678-9",
            email="cliente@test.com"
        )
    print(f"\n✅ Cliente: {cliente.nombre} (ID: {cliente.id})")
except Exception as e:
    print(f"❌ Error con cliente: {e}")
    exit(1)

# 3. Obtener o crear proyectos
try:
    proyecto_a = Proyecto.objects.filter(empresa_interna=empresa_a).first()
    if not proyecto_a:
        proyecto_a = Proyecto.objects.create(
            nombre="Proyecto A1",
            empresa_interna=empresa_a,
            cliente=cliente,
            tipo_texto="Test"
        )
    
    proyecto_b = Proyecto.objects.filter(empresa_interna=empresa_b).first()
    if not proyecto_b:
        proyecto_b = Proyecto.objects.create(
            nombre="Proyecto B1",
            empresa_interna=empresa_b,
            cliente=cliente,
            tipo_texto="Test"
        )
    
    print(f"\n✅ Proyecto A: {proyecto_a.nombre} (ID: {proyecto_a.id}, Empresa: {empresa_a.nombre})")
    print(f"✅ Proyecto B: {proyecto_b.nombre} (ID: {proyecto_b.id}, Empresa: {empresa_b.nombre})")
except Exception as e:
    print(f"❌ Error creando proyectos: {e}")
    exit(1)

# 4. Crear tareas en ambos proyectos
try:
    tarea_a1, _ = Tarea.objects.get_or_create(
        nombre="Tarea A1",
        proyecto=proyecto_a,
        defaults={'tipo_tarea': None, 'estado': 'PENDIENTE'}
    )
    
    tarea_a2, _ = Tarea.objects.get_or_create(
        nombre="Tarea A2",
        proyecto=proyecto_a,
        defaults={'tipo_tarea': None, 'estado': 'PENDIENTE'}
    )
    
    tarea_b1, _ = Tarea.objects.get_or_create(
        nombre="Tarea B1",
        proyecto=proyecto_b,
        defaults={'tipo_tarea': None, 'estado': 'PENDIENTE'}
    )
    
    print(f"\n✅ Tareas en Proyecto A: {tarea_a1.nombre}, {tarea_a2.nombre}")
    print(f"✅ Tareas en Proyecto B: {tarea_b1.nombre}")
except Exception as e:
    print(f"❌ Error creando tareas: {e}")
    exit(1)

# 5. TEST 1: Verificar queryset de "depende_de" para Proyecto A
print("\n" + "-"*80)
print("TEST 1: Queryset de 'depende_de' en Proyecto A")
print("-"*80)

try:
    form_a = TareaForm(proyecto_id=proyecto_a.id)
    depende_de_qs_a = form_a.fields['depende_de'].queryset
    
    print(f"\n📋 Total tareas en sistema: {Tarea.objects.count()}")
    print(f"📋 Queryset 'depende_de' para Proyecto A: {depende_de_qs_a.count()} tareas")
    print(f"   Tareas mostradas:")
    for t in depende_de_qs_a:
        print(f"   - {t.nombre} (Proyecto: {t.proyecto.nombre})")
    
    # Verificar que SOLO muestra tareas de Proyecto A
    tareas_proyecto_a_en_form = [t.id for t in depende_de_qs_a if t.proyecto_id == proyecto_a.id]
    tareas_otras_en_form = [t.id for t in depende_de_qs_a if t.proyecto_id != proyecto_a.id]
    
    if len(tareas_otras_en_form) == 0 and depende_de_qs_a.count() == 2:
        print(f"\n✅ CORRECTO: Solo muestra {depende_de_qs_a.count()} tareas de Proyecto A")
    else:
        print(f"\n❌ ERROR: Muestra {len(tareas_otras_en_form)} tareas de otros proyectos")
    
except Exception as e:
    print(f"❌ Error en test 1: {e}")

# 6. TEST 2: Verificar queryset de "depende_de" para Proyecto B
print("\n" + "-"*80)
print("TEST 2: Queryset de 'depende_de' en Proyecto B")
print("-"*80)

try:
    form_b = TareaForm(proyecto_id=proyecto_b.id)
    depende_de_qs_b = form_b.fields['depende_de'].queryset
    
    print(f"\n📋 Queryset 'depende_de' para Proyecto B: {depende_de_qs_b.count()} tareas")
    print(f"   Tareas mostradas:")
    for t in depende_de_qs_b:
        print(f"   - {t.nombre} (Proyecto: {t.proyecto.nombre})")
    
    # Verificar segregación
    tareas_proyecto_b_en_form = [t.id for t in depende_de_qs_b if t.proyecto_id == proyecto_b.id]
    tareas_proyecto_a_en_form_b = [t.id for t in depende_de_qs_b if t.proyecto_id == proyecto_a.id]
    
    if depende_de_qs_b.count() == 1 and len(tareas_proyecto_a_en_form_b) == 0:
        print(f"\n✅ CORRECTO: Solo muestra tarea de Proyecto B, nada de Proyecto A")
    else:
        print(f"\n❌ ERROR: Segregación violada - muestra {len(tareas_proyecto_a_en_form_b)} tareas de Proyecto A")
    
except Exception as e:
    print(f"❌ Error en test 2: {e}")

# 7. TEST 3: Verificar que campo "proyecto" se bloquea
print("\n" + "-"*80)
print("TEST 3: Campo 'proyecto' debe estar deshabilitado")
print("-"*80)

try:
    form_a = TareaForm(proyecto_id=proyecto_a.id)
    proyecto_field = form_a.fields['proyecto']
    
    if proyecto_field.disabled:
        print(f"\n✅ CORRECTO: Campo 'proyecto' está deshabilitado (disabled=True)")
    else:
        print(f"\n❌ ERROR: Campo 'proyecto' NO está deshabilitado")
    
    print(f"   Queryset del campo: {list(proyecto_field.queryset.values_list('nombre', flat=True))}")
    
except Exception as e:
    print(f"❌ Error en test 3: {e}")

# 8. TEST 4: Validación de clean() - rechazar dependencia de otro proyecto
print("\n" + "-"*80)
print("TEST 4: Validación clean() - rechazar tarea de otro proyecto")
print("-"*80)

try:
    # Intentar crear formulario con "depende_de" de proyecto diferente
    form_data = {
        'nombre': 'Tarea A3',
        'descripcion': 'Test',
        'proyecto': proyecto_a.id,
        'tipo_tarea': '',
        'profesional_asignado': '',
        'estado': 'PENDIENTE',
        'prioridad': 'MEDIA',
        'depende_de': [tarea_b1.id],  # ← Tarea de OTRO proyecto
        'porcentaje_avance': 0,
    }
    
    form = TareaForm(form_data, proyecto_id=proyecto_a.id)
    
    if not form.is_valid():
        print(f"\n✅ CORRECTO: Formulario rechaza dependencia de otro proyecto")
        print(f"   Errores: {form.errors}")
    else:
        print(f"\n❌ ERROR: Formulario acepta dependencia de otro proyecto (debería rechazar)")
    
except Exception as e:
    print(f"❌ Error en test 4: {e}")

print("\n" + "="*80)
print("TESTS COMPLETADOS")
print("="*80 + "\n")
