# ✅ CHECKLIST RÁPIDO: Verificar que funciona

## 🎯 Paso 1: Reinicia Django (5 segundos)

Si Django ya está corriendo:
```bash
# Presiona Ctrl+C en el terminal donde corre Django
# Luego:
python manage.py runserver
```

**Razón:** settings.py tiene que recargar para aplicar CSRF_TRUSTED_ORIGINS

---

## 🎯 Paso 2: Abre el navegador (30 segundos)

1. Abre: `http://localhost:8000/control-proyectos/proyectos/1/`
2. Presiona `F12` para abrir DevTools
3. Ve a la pestaña `Console`
4. Busca mensajes que comienzan con 🔄 🔴 📬 ✅

---

## 🎯 Paso 3: Mueve el slider (10 segundos)

En la página, encuentra una tarea y mueve su slider de avance.

**Verás en Console:**
```
🔄 Enviando POST a avance: { 
    url: '/control-proyectos/tareas/4/avance/', 
    tareaId: 4, 
    payload: { porcentaje_avance: 50 }
}

📬 Response recibido: { 
    status: 200, 
    statusText: 'OK'
}

✅ JSON parseado: { 
    success: true, 
    porcentaje_avance: 50
}

✓ Avance actualizado: Avance actualizado a 50%
```

---

## ✅ Señales de ÉXITO

- [ ] En Console ves `status: 200` (no 403)
- [ ] En Console ves `success: true`
- [ ] El slider se movió suavemente
- [ ] Aparece el toast verde diciendo "Avance actualizado..."
- [ ] En Admin/BD, el porcentaje cambió

**Si todo ✓ → PROBLEMA RESUELTO**

---

## ❌ Si ves 403 nuevamente

### 1. Verifica que reiniciaste Django
```bash
# En el terminal de Django, debe decir:
Starting development server at http://127.0.0.1:8000/
```

### 2. Verifica CSRF_TRUSTED_ORIGINS en settings.py
Abre [AppDocs/settings.py](../AppDocs/settings.py#L250) línea 250:

```python
CSRF_TRUSTED_ORIGINS = [
    "https://biblioteca.eltit.cl",
    "http://localhost:8000",       ← Debe estar
    "http://127.0.0.1:8000",       ← Debe estar
    "http://localhost:8000:*",     ← Debe estar
    "http://127.0.0.1:8000:*"      ← Debe estar
]
```

### 3. Borra cache del navegador
- Presiona `Ctrl+Shift+Delete`
- Selecciona "Cookies" y "Cache"
- Borra para "localhost"

### 4. Recarga la página
- `Ctrl+F5` (reload sin cache)
- Intenta slider nuevamente

---

## ⏱️ Tiempo Total: 2-3 minutos

| Paso | Tiempo | Status |
|------|--------|--------|
| 1. Reiniciar Django | 5 seg | ⏳ |
| 2. Abrir navegador | 30 seg | ⏳ |
| 3. Mover slider | 10 seg | ⏳ |
| Verificación | 30 seg | ⏳ |
| **TOTAL** | **~2 min** | |

---

## 🔍 Troubleshooting

| Síntoma | Causa | Solución |
|---------|-------|----------|
| `status: 403` | CSRF_TRUSTED_ORIGINS no actualizado | Verifica línea 250 de settings.py |
| `status: 404` | Ruta equivocada | Verifica URL en barra de direcciones |
| `status: 500` | Error en endpoint | Mira terminal de Django para error |
| No aparecen logs | Logging no activado | Verifica proyecto_detalle.html |
| `csrfToken: 'FALTANTE'` | Cookie CSRF no existe | Recarga página, espera cookies |

---

## 📞 Si nada funciona

Ejecuta este test directo desde terminal:

```bash
python test_post_simple.py
```

**Si retorna Status 200:** Problema es solo en navegador (cache, cookies, etc.)
**Si retorna 403:** Problema en settings.py

Envía el output del test para diagnosticar.

---

## ✨ ¡Listo!

Una vez que confirmes Status 200, puedes:
- ✅ Cerrar DevTools
- ✅ Seguir usando la app normalmente
- ✅ El slider funcionará en cualquier tarea
