Documenta como COMPLETADO el requerimiento "Recuérdame" del login y agrégalo a la documentación base del sistema dentro de /COPILOT/.

Antes de modificar:
- Lee Paracopilot.md.
- Revisa las reglas/documentación existente en /COPILOT/.
- No modifiques código funcional.
- Este trabajo es SOLO documentación.

Crear, preferentemente:

/COPILOT/LOGIN_RECUERDAME_SESIONES.md

Documentar lo siguiente:

# Login - Recuérdame y seguridad de sesión

## Estado

COMPLETADO
VALIDADO EN PRODUCCIÓN: 21-08-2026

## Objetivo

El checkbox "Recuérdame" del login debe controlar la duración de la sesión de Django.

No se deben almacenar username, password, sessionid ni credenciales en localStorage/sessionStorage.

La autenticación continúa utilizando el sistema de sesiones de Django mediante cookie sessionid.

## Comportamiento

### Recuérdame marcado

El formulario envía:

name="remember_me"
value="1"

Después de autenticar correctamente:

request.session.set_expiry(8 * 60 * 60)

La sesión queda vigente durante:

28.800 segundos = 8 horas.

Las 8 horas representan una jornada laboral extensa y son la política definida para esta aplicación.

### Recuérdame NO marcado

Se ejecuta:

request.session.set_expiry(0)

La cookie queda como cookie de sesión y expira al cerrar el navegador.

## Seguridad

La sesión NO se almacena en localStorage ni sessionStorage.

La cookie sessionid es gestionada por Django.

Configuración productiva validada:

SESSION_COOKIE_SECURE=True
CSRF_COOKIE_SECURE=True
DJANGO_BEHIND_HTTPS_PROXY=True

Django obtiene:

SECURE_PROXY_SSL_HEADER = (
    "HTTP_X_FORWARDED_PROTO",
    "https",
)

Nginx es el responsable de HTTPS y envía:

proxy_set_header X-Forwarded-Proto https;

SECURE_SSL_REDIRECT permanece False porque la redirección HTTP -> HTTPS es responsabilidad de Nginx.

## Arquitectura productiva

Internet
  -> Nginx HTTP/HTTPS
  -> redirect HTTP a HTTPS
  -> Nginx TLS
  -> proxy_pass http://127.0.0.1:8000
  -> Docker biblioteca-web
  -> Django

## Cookie sessionid validada en producción

Se realizó login real marcando "Recuérdame".

Chrome DevTools confirmó:

- sessionid presente
- HttpOnly = True
- Secure = True
- SameSite = Lax
- expiración = hora de login + 8 horas

Ejemplo validado:

login aproximadamente 14:46
expiración aproximadamente 22:46

Por lo tanto, la duración real observada fue de 8 horas.

## Cookie CSRF validada

Se verificó también en producción:

csrftoken
Secure = True
SameSite = Lax

## DEBUG

Actualmente producción mantiene:

DEBUG=True

IMPORTANTE:

DEBUG=False NO es requisito para que funcione Recuérdame ni para utilizar SESSION_COOKIE_SECURE.

No cambiar DEBUG como parte de este requerimiento.

Existe trabajo futuro para preparar correctamente static/media antes de pasar producción a DEBUG=False.

## Nginx

Producción ya fuerza HTTPS:

listen 80
-> return 301 https://$host$request_uri

HTTPS utiliza:

listen 443 ssl

y entrega a Django:

proxy_set_header X-Forwarded-Proto https

No modificar esta arquitectura como parte del requerimiento Recuérdame.

## Configuración por entorno

AppDocs/settings.py permite actualmente:

DJANGO_DEBUG
DJANGO_SECRET_KEY
DJANGO_ALLOWED_HOSTS
DJANGO_CSRF_TRUSTED_ORIGINS
SESSION_COOKIE_SECURE
CSRF_COOKIE_SECURE
DJANGO_BEHIND_HTTPS_PROXY

En producción actualmente se configuraron:

SESSION_COOKIE_SECURE=True
CSRF_COOKIE_SECURE=True
DJANGO_BEHIND_HTTPS_PROXY=True

mediante /AppDocs/.env.

No documentar valores de secretos BUK, SII, SECRET_KEY ni otras credenciales.

## Tests

Existe cobertura específica para:

- Recuérdame marcado
- expiración de 8 horas
- Recuérdame no marcado
- expiración al cerrar navegador
- credenciales inválidas
- logout
- ausencia de almacenamiento frontend de credenciales
- configuración de seguridad por entorno

La suite combinada ejecutada durante el desarrollo pasó correctamente.

## Regla para futuros desarrollos

NO reemplazar este mecanismo por localStorage.

NO almacenar contraseñas.

NO almacenar sessionid manualmente.

NO implementar tokens frontend para reemplazar la sesión Django del sitio web.

Para autenticación web normal debe mantenerse:

Django authentication
+
Django session
+
cookie HttpOnly/Secure
+
set_expiry()

Las APIs destinadas a integraciones externas pueden utilizar su propio mecanismo de token/API key y deben mantenerse conceptualmente separadas de la autenticación web del usuario.

## Archivos relacionados

Documentar las rutas reales encontradas en el repositorio, incluyendo como mínimo:

- acounts/views.py
- templates/pages/authentication/auth-signin-basic.html
- AppDocs/settings.py
- acounts/tests/test_login_session_expiry.py
- acounts/tests/test_security_settings.py

Si alguna ruta cambió, utilizar la ruta real encontrada en el repositorio.

## Cierre

Marcar explícitamente:

REQUERIMIENTO: LOGIN "RECUÉRDAME"
ESTADO: COMPLETADO
DESARROLLO: VALIDADO
TESTS: OK
PRODUCCIÓN: VALIDADA
HTTPS/COOKIE SECURE: VALIDADO
DURACIÓN 8 HORAS: VALIDADA

Finalmente, si existe un índice, README, mapa o resumen maestro dentro de /COPILOT/ destinado a registrar funcionalidades base terminadas, agregar una referencia breve al nuevo documento sin reestructurar la documentación existente.

No modificar código.
No modificar settings.
No modificar .env.
No modificar Docker.
No modificar Nginx.
Solo documentación.