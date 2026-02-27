from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import render, redirect
from django.views import View
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from .models import UserPreferences, ThemePreferences
from django.contrib import messages
from django import forms
from datetime import date
import re
import imaplib
import poplib
import smtplib
from django.db import transaction
from django.http import JsonResponse
from email.utils import formatdate, make_msgid
from email.message import EmailMessage
from email.parser import BytesParser
from email.policy import default
import json
import mimetypes
import os

from access_control.decorators import verificar_permiso
from access_control.views import VerificarPermisoMixin
from access_control.models import Vista, Permiso
from access_control.services.access_requests import build_access_request_context
from .models import SettingsMySQLConnection
from .forms import SettingsMySQLConnectionForm
from django.views.generic import ListView, CreateView, UpdateView, DeleteView
from django.urls import reverse_lazy
from django.http import HttpResponse
from django.db import connections
import hashlib
from django.conf import settings


def _require_empresa_activa_for_view(request, vista_nombre):
    """Verifica que el usuario tenga empresa activa en sesión."""
    empresa_id = request.session.get("empresa_id")
    if not empresa_id:
        contexto = build_access_request_context(
            request,
            vista_nombre,
            "No tienes permisos suficientes para acceder a esta página.",
        )
        return render(request, "access_control/403_forbidden.html", contexto, status=403)
    return None


# ============================================================================
# CBVs: Settings Email Testing
# ============================================================================

class ProbarConfiguracionEntradaView(VerificarPermisoMixin, LoginRequiredMixin, View):
    """Probar conexión con servidor de correo de entrada (IMAP/POP3)."""
    vista_nombre = "Settings - Probar Configuración Entrada"
    permiso_requerido = "ingresar"

    def dispatch(self, request, *args, **kwargs):
        empresa_response = _require_empresa_activa_for_view(request, self.vista_nombre)
        if empresa_response:
            return empresa_response
        return super().dispatch(request, *args, **kwargs)

    def post(self, request, *args, **kwargs):
        try:
            protocolo = request.POST.get("protocolo")
            host = request.POST.get("servidor")
            port = int(request.POST.get("puerto"))
            user = request.POST.get("usuario")
            password = request.POST.get("contrasena")
            encryption = request.POST.get("encriptacion")

            if protocolo == "IMAP":
                if encryption == "SSL":
                    mail = imaplib.IMAP4_SSL(host, port)
                else:
                    mail = imaplib.IMAP4(host, port)
                    if encryption == "TLS":
                        mail.starttls()
                mail.login(user, password)
                mail.logout()
            else:  # POP3
                if encryption == "SSL":
                    mail = poplib.POP3_SSL(host, port)
                else:
                    mail = poplib.POP3(host, port)
                mail.user(user)
                mail.pass_(password)
                mail.quit()
            return JsonResponse({"success": True})
        except Exception as e:
            return JsonResponse({"success": False, "error": str(e)})


class ProbarConfiguracionSalidaView(VerificarPermisoMixin, LoginRequiredMixin, View):
    """Probar conexión con servidor SMTP."""
    vista_nombre = "Settings - Probar Configuración Salida"
    permiso_requerido = "ingresar"

    def dispatch(self, request, *args, **kwargs):
        empresa_response = _require_empresa_activa_for_view(request, self.vista_nombre)
        if empresa_response:
            return empresa_response
        return super().dispatch(request, *args, **kwargs)

    def post(self, request, *args, **kwargs):
        try:
            host = request.POST.get("smtp_host")
            port = int(request.POST.get("smtp_port"))
            user = request.POST.get("smtp_username")
            password = request.POST.get("smtp_password")
            encryption = request.POST.get("smtp_encryption")

            if encryption == "SSL":
                server = smtplib.SMTP_SSL(host, port, timeout=10)
            else:
                server = smtplib.SMTP(host, port, timeout=10)
                if encryption == "STARTTLS":
                    server.starttls()

            server.login(user, password)
            server.quit()
            return JsonResponse({"success": True})
        except Exception as e:
            return JsonResponse({"success": False, "error": str(e)})


class EnviarCorreoPruebaView(VerificarPermisoMixin, LoginRequiredMixin, View):
    """Enviar correo de prueba usando configuración SMTP del usuario."""
    vista_nombre = "Settings - Enviar Correo Prueba"
    permiso_requerido = "ingresar"

    def dispatch(self, request, *args, **kwargs):
        empresa_response = _require_empresa_activa_for_view(request, self.vista_nombre)
        if empresa_response:
            return empresa_response
        return super().dispatch(request, *args, **kwargs)

    def post(self, request, *args, **kwargs):
        try:
            prefs = UserPreferences.objects.get(user=request.user)

            # Validar campos esenciales
            if not prefs.smtp_host or not prefs.smtp_username or not prefs.smtp_password:
                return JsonResponse({"success": False, "error": "Configuración SMTP incompleta."})

            # Preparar correo
            msg = EmailMessage()
            msg["Subject"] = "Correo de prueba desde el sistema"
            msg["From"] = prefs.smtp_username
            msg["To"] = prefs.smtp_username
            msg["Date"] = formatdate(localtime=True)
            msg["Message-ID"] = make_msgid()
            msg["X-Mailer"] = "Sistema ERP-Django"

            # Cuerpo en texto plano y HTML
            msg.set_content("Este es un correo de prueba desde el sistema.")
            msg.add_alternative("""
            <html>
                <body>
                    <p>Este es un <strong>correo de prueba</strong> enviado desde tu sistema.</p>
                </body>
            </html>
            """, subtype='html')

            # Adjuntar avatar si existe y es accesible
            if hasattr(request.user, "avatar") and request.user.avatar.imagen:
                avatar_path = request.user.avatar.imagen.path
                if os.path.exists(avatar_path):
                    mime_type, _ = mimetypes.guess_type(avatar_path)
                    if mime_type:
                        maintype, subtype = mime_type.split('/')
                        with open(avatar_path, 'rb') as f:
                            msg.add_attachment(
                                f.read(),
                                maintype=maintype,
                                subtype=subtype,
                                filename=os.path.basename(avatar_path)
                            )

            # Conexión SMTP
            if prefs.smtp_encryption == "SSL":
                server = smtplib.SMTP_SSL(prefs.smtp_host, prefs.smtp_port)
            else:
                server = smtplib.SMTP(prefs.smtp_host, prefs.smtp_port)
                if prefs.smtp_encryption == "STARTTLS":
                    server.starttls()

            server.login(prefs.smtp_username, prefs.smtp_password)
            server.send_message(msg)
            server.quit()

            return JsonResponse({"success": True})
        except Exception as e:
            return JsonResponse({"success": False, "error": str(e)})


class RecibirCorreoPruebaView(VerificarPermisoMixin, LoginRequiredMixin, View):
    """Recibir correo de prueba desde servidor de entrada."""
    vista_nombre = "Settings - Recibir Correo Prueba"
    permiso_requerido = "ingresar"

    def dispatch(self, request, *args, **kwargs):
        empresa_response = _require_empresa_activa_for_view(request, self.vista_nombre)
        if empresa_response:
            return empresa_response
        return super().dispatch(request, *args, **kwargs)

    def post(self, request, *args, **kwargs):
        try:
            prefs = UserPreferences.objects.get(user=request.user)
            if not prefs.email_host or not prefs.email_username or not prefs.email_password:
                return JsonResponse({"success": False, "error": "Configuración de correo de entrada incompleta."})

            protocolo = prefs.email_protocol
            if protocolo == "IMAP":
                # No implementado aún
                return JsonResponse({"success": False, "error": "IMAP aún no implementado."})
            else:  # POP3
                if prefs.email_encryption == "SSL":
                    server = poplib.POP3_SSL(prefs.email_host, prefs.email_port)
                else:
                    server = poplib.POP3(prefs.email_host, prefs.email_port)

                server.user(prefs.email_username)
                server.pass_(prefs.email_password)

                num_messages = len(server.list()[1])
                if num_messages == 0:
                    return JsonResponse({"success": False, "error": "Bandeja de entrada vacía."})

                # Obtener el último mensaje
                response, lines, octets = server.retr(num_messages)
                msg_content = b"\r\n".join(lines)
                msg = BytesParser(policy=default).parsebytes(msg_content)

                subject = msg["subject"]
                server.quit()
                return JsonResponse({"success": True, "subject": subject})
        except Exception as e:
            return JsonResponse({"success": False, "error": str(e)})


class SetFechaSistemaView(VerificarPermisoMixin, LoginRequiredMixin, View):
    """Configurar fecha del sistema."""
    vista_nombre = "Settings - Establecer Fecha Sistema"
    permiso_requerido = "ingresar"

    def dispatch(self, request, *args, **kwargs):
        empresa_response = _require_empresa_activa_for_view(request, self.vista_nombre)
        if empresa_response:
            return empresa_response
        return super().dispatch(request, *args, **kwargs)

    def post(self, request, *args, **kwargs):
        fecha_str = (request.POST.get("fecha_sistema") or "").strip()

        if not re.match(r"^\d{4}-\d{2}-\d{2}$", fecha_str):
            return JsonResponse({"ok": False, "error_key": "system_date.error.invalid"}, status=400)

        try:
            fecha = date.fromisoformat(fecha_str)
        except ValueError:
            return JsonResponse({"ok": False, "error_key": "system_date.error.invalid"}, status=400)

        try:
            prefs, _ = UserPreferences.objects.get_or_create(user=request.user)
            prefs.fecha_sistema = fecha
            prefs.save(update_fields=["fecha_sistema"])
            request.session["fecha_sistema"] = fecha_str
            return JsonResponse({"ok": True, "fecha_sistema": fecha_str})
        except Exception:
            return JsonResponse({"ok": False, "error_key": "system_date.error.server"}, status=500)


# ============================================================================
# Email Configuration
# ============================================================================

class EmailSettingsForm(forms.ModelForm):
    class Meta:
        model = UserPreferences
        fields = [
            'email_enabled', 'email_protocol', 'email_host', 'email_port',
            'email_encryption', 'email_username', 'email_password',
            'smtp_host', 'smtp_port', 'smtp_encryption', 'smtp_username', 'smtp_password',
            'send_headers', 'send_documents'
        ]
        widgets = {
            'email_password': forms.PasswordInput(render_value=True),
            'smtp_password': forms.PasswordInput(render_value=True),
        }


class ConfigurarEmailView(LoginRequiredMixin, View):
    """Configurar preferencias de correo electrónico."""
    
    def get(self, request, *args, **kwargs):
        preferencias, _ = UserPreferences.objects.get_or_create(user=request.user)
        form = EmailSettingsForm(instance=preferencias)
        return render(request, 'configurar_email.html', {'form': form})

    def post(self, request, *args, **kwargs):
        preferencias, _ = UserPreferences.objects.get_or_create(user=request.user)
        form = EmailSettingsForm(request.POST, instance=preferencias)
        if form.is_valid():
            form.save()
            messages.success(request, "Preferencias de correo guardadas correctamente.")
            return redirect('configurar_email')
        return render(request, 'configurar_email.html', {'form': form})


# ============================================================================
# Theme Preferences (with decorator-based permiso check)
# ============================================================================

@login_required
@require_POST
@verificar_permiso("Settings - Theme preference", "modificar")
def guardar_preferencias(request):
    """Guardar preferencias de tema del usuario."""
    try:
        data = json.loads(request.body.decode("utf-8") or "{}")
    except json.JSONDecodeError:
        return JsonResponse({"success": False, "error": "JSON inválido"}, status=400)

    empresa_id = request.session.get("empresa_id")
    if not empresa_id:
        return JsonResponse({"success": False, "error": "Empresa no seleccionada"}, status=400)

    prefs, _ = ThemePreferences.objects.get_or_create(user=request.user, empresa_id=empresa_id)

    field_map = {
        "data-layout": "data_layout",
        "data-bs-theme": "data_bs_theme",
        "data-sidebar-visibility": "data_sidebar_visibility",
        "data-layout-width": "data_layout_width",
        "data-layout-position": "data_layout_position",
        "data-topbar": "data_topbar",
        "data-sidebar-size": "data_sidebar_size",
        "data-layout-style": "data_layout_style",
        "data-sidebar": "data_sidebar",
        "data-sidebar-image": "data_sidebar_image",
        "data-preloader": "data_preloader",
    }

    updated = {}
    for key, field in field_map.items():
        if key in data:
            value = data.get(key)
            if value is not None and value != "":
                setattr(prefs, field, value)
                updated[key] = value

    if updated:
        prefs.save(update_fields=[field_map[key] for key in updated])

    return JsonResponse({"success": True, "updated": updated})


# ============================================================================
# MySQL Connections CRUD
# ============================================================================


class MySQLConnectionListView(VerificarPermisoMixin, LoginRequiredMixin, ListView):
    model = SettingsMySQLConnection
    template_name = 'settings/mysql_connections_list.html'
    context_object_name = 'connections'
    vista_nombre = 'Settings - Conexiones MySQL'
    permiso_requerido = 'ingresar'

    def dispatch(self, request, *args, **kwargs):
        empresa_id = request.session.get('empresa_id')
        if not empresa_id:
            contexto = build_access_request_context(request, self.vista_nombre, 'Empresa activa requerida')
            return render(request, 'access_control/403_forbidden.html', contexto, status=403)
        return super().dispatch(request, *args, **kwargs)

    def get_queryset(self):
        empresa_id = self.request.session.get('empresa_id')
        return SettingsMySQLConnection.objects.filter(empresa_id=empresa_id)


class MySQLConnectionCreateView(VerificarPermisoMixin, LoginRequiredMixin, CreateView):
    model = SettingsMySQLConnection
    form_class = SettingsMySQLConnectionForm
    template_name = 'settings/mysql_connection_form.html'
    success_url = reverse_lazy('mysql_connections_list')
    vista_nombre = 'Settings - Conexiones MySQL'
    permiso_requerido = 'crear'

    def dispatch(self, request, *args, **kwargs):
        empresa_id = request.session.get('empresa_id')
        if not empresa_id:
            contexto = build_access_request_context(request, self.vista_nombre, 'Empresa activa requerida')
            return render(request, 'access_control/403_forbidden.html', contexto, status=403)
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        empresa_id = self.request.session.get('empresa_id')
        form.instance.empresa_id = empresa_id
        return super().form_valid(form)


class MySQLConnectionUpdateView(VerificarPermisoMixin, LoginRequiredMixin, UpdateView):
    model = SettingsMySQLConnection
    form_class = SettingsMySQLConnectionForm
    template_name = 'settings/mysql_connection_form.html'
    success_url = reverse_lazy('mysql_connections_list')
    vista_nombre = 'Settings - Conexiones MySQL'
    permiso_requerido = 'modificar'

    def dispatch(self, request, *args, **kwargs):
        empresa_id = request.session.get('empresa_id')
        if not empresa_id:
            contexto = build_access_request_context(request, self.vista_nombre, 'Empresa activa requerida')
            return render(request, 'access_control/403_forbidden.html', contexto, status=403)
        # Ensure object belongs to empresa
        obj = self.get_object()
        if obj.empresa_id != empresa_id:
            return render(request, 'access_control/403_forbidden.html', build_access_request_context(request, self.vista_nombre, 'Acceso denegado'), status=403)
        return super().dispatch(request, *args, **kwargs)


class MySQLConnectionDeleteView(VerificarPermisoMixin, LoginRequiredMixin, DeleteView):
    model = SettingsMySQLConnection
    template_name = 'settings/mysql_connection_confirm_delete.html'
    success_url = reverse_lazy('mysql_connections_list')
    vista_nombre = 'Settings - Conexiones MySQL'
    permiso_requerido = 'eliminar'

    def dispatch(self, request, *args, **kwargs):
        empresa_id = request.session.get('empresa_id')
        if not empresa_id:
            contexto = build_access_request_context(request, self.vista_nombre, 'Empresa activa requerida')
            return render(request, 'access_control/403_forbidden.html', contexto, status=403)
        obj = self.get_object()
        if obj.empresa_id != empresa_id:
            return render(request, 'access_control/403_forbidden.html', build_access_request_context(request, self.vista_nombre, 'Acceso denegado'), status=403)
        return super().dispatch(request, *args, **kwargs)

    def post(self, request, *args, **kwargs):
        is_ajax = (
            request.META.get('HTTP_X_REQUESTED_WITH') == 'XMLHttpRequest' or
            'application/json' in request.META.get('HTTP_ACCEPT', '')
        )
        try:
            self.object = self.get_object()
            nombre = str(self.object)
            self.object.delete()
            if is_ajax:
                return JsonResponse({'success': True, 'message': 'connection_deleted', 'deleted_name': nombre})
            return redirect(self.success_url)
        except Exception as e:
            if is_ajax:
                return JsonResponse({'success': False, 'message': 'request_error'}, status=500)
            return redirect(self.success_url)


class MySQLConnectionTestView(VerificarPermisoMixin, LoginRequiredMixin, View):
    vista_nombre = 'Settings - Conexiones MySQL'
    permiso_requerido = 'ingresar'

    def dispatch(self, request, *args, **kwargs):
        empresa_id = request.session.get('empresa_id')
        if not empresa_id:
            contexto = build_access_request_context(request, self.vista_nombre, 'Empresa activa requerida')
            return render(request, 'access_control/403_forbidden.html', contexto, status=403)

        pk = kwargs.get('pk')
        try:
            obj = SettingsMySQLConnection.objects.get(pk=pk)
        except SettingsMySQLConnection.DoesNotExist:
            return JsonResponse({'success': False, 'tables': [], 'count': 0, 'message_key': 'settings.mysql_connections.test_error'}, status=404)

        if obj.empresa_id != empresa_id:
            return JsonResponse({'success': False, 'tables': [], 'count': 0, 'message_key': 'settings.mysql_connections.forbidden'}, status=403)

        self.obj = obj
        self.empresa_id = empresa_id
        return super().dispatch(request, *args, **kwargs)

    def get(self, request, *args, **kwargs):
        # Prepare alias
        alias_base = f"test_mysql_{self.empresa_id}_{self.obj.pk}"
        alias = alias_base

        cfg = self.obj

        # Build complete DB config based on settings.DATABASES['default']
        base_config = {}
        try:
            base_config = settings.DATABASES.get('default', {}).copy()
        except Exception:
            base_config = {}

        # Ensure base_config is a dict and does not contain None
        if not isinstance(base_config, dict):
            base_config = {}

        complete_cfg = base_config.copy()
        complete_cfg.update({
            'ENGINE': 'django.db.backends.mysql',
            'NAME': cfg.db_name,
            'USER': cfg.user,
            'PASSWORD': cfg.password,
            'HOST': cfg.host,
            'PORT': str(cfg.port or ''),
            'OPTIONS': {'charset': 'utf8mb4'},
            'CONN_MAX_AGE': 0,
            'ATOMIC_REQUESTS': False,
        })

        # Prepare new complete config
        new_config = complete_cfg

        # If alias exists, compare key connection fields (excluding password)
        existing = connections.databases.get(alias)
        if existing is not None:
            try:
                same_connection = (
                    str(existing.get('NAME', '')) == str(new_config.get('NAME', '')) and
                    str(existing.get('HOST', '')) == str(new_config.get('HOST', '')) and
                    str(existing.get('USER', '')) == str(new_config.get('USER', '')) and
                    str(existing.get('PORT', '')) == str(new_config.get('PORT', ''))
                )
            except Exception:
                same_connection = False

            if not same_connection:
                # Close any existing connection for this alias before replacing
                try:
                    connections[alias].close()
                except Exception:
                    pass
                connections.databases[alias] = new_config
            else:
                # Ensure required runtime keys exist; if any missing, replace entirely
                required_keys = ('ATOMIC_REQUESTS', 'CONN_MAX_AGE', 'ENGINE', 'NAME', 'USER', 'PASSWORD', 'HOST', 'PORT', 'OPTIONS')
                missing = any(k not in existing for k in required_keys)
                if missing:
                    try:
                        connections[alias].close()
                    except Exception:
                        pass
                    connections.databases[alias] = new_config
                else:
                    # reuse existing
                    pass
        else:
            # alias not present: register complete config
            connections.databases[alias] = new_config

        try:
            with connections[alias].cursor() as cursor:
                cursor.execute("SHOW TABLES")
                rows = cursor.fetchall()
                tables = [r[0] for r in rows][:20]
                count = len(rows)
        except Exception:
            # Do not expose error details
            return JsonResponse({'success': False, 'tables': [], 'count': 0, 'message_key': 'settings.mysql_connections.test_error'})
        finally:
            try:
                connections[alias].close()
            except Exception:
                pass

        return JsonResponse({'success': True, 'tables': tables, 'count': count, 'message_key': 'settings.mysql_connections.test_success'})


class MySQLConnectionsExportView(VerificarPermisoMixin, LoginRequiredMixin, View):
    vista_nombre = 'Settings - Conexiones MySQL'
    permiso_requerido = 'ingresar'

    def dispatch(self, request, *args, **kwargs):
        empresa_id = request.session.get('empresa_id')
        if not empresa_id:
            contexto = build_access_request_context(request, self.vista_nombre, 'Empresa activa requerida')
            return render(request, 'access_control/403_forbidden.html', contexto, status=403)
        return super().dispatch(request, *args, **kwargs)

    def get(self, request, *args, **kwargs):
        empresa_id = request.session.get('empresa_id')
        qs = SettingsMySQLConnection.objects.filter(empresa_id=empresa_id)
        connections = []
        for c in qs:
            connections.append({
                'nombre_logico': c.nombre_logico,
                'host': c.host,
                'port': int(c.port or 3306),
                'user': c.user,
                'password': c.password,
                'db_name': c.db_name,
                'is_active': bool(c.is_active),
            })

        payload = {
            'version': 1,
            'empresa_id': empresa_id,
            'exported_at': formatdate(localtime=True),
            'connections': connections,
        }

        content = json.dumps(payload, ensure_ascii=False)
        resp = HttpResponse(content, content_type='application/json; charset=utf-8')
        resp['Content-Disposition'] = 'attachment; filename="conexionesMysql.cfg"'
        return resp


class MySQLConnectionsImportView(VerificarPermisoMixin, LoginRequiredMixin, View):
    vista_nombre = 'Settings - Conexiones MySQL'
    permiso_requerido = 'modificar'

    def dispatch(self, request, *args, **kwargs):
        empresa_id = request.session.get('empresa_id')
        if not empresa_id:
            contexto = build_access_request_context(request, self.vista_nombre, 'Empresa activa requerida')
            return render(request, 'access_control/403_forbidden.html', contexto, status=403)
        return super().dispatch(request, *args, **kwargs)

    def post(self, request, *args, **kwargs):
        is_ajax = (
            request.META.get('HTTP_X_REQUESTED_WITH') == 'XMLHttpRequest' or
            'application/json' in request.META.get('HTTP_ACCEPT', '')
        )

        uploaded = request.FILES.get('conexionesMysql.cfg') or (next(iter(request.FILES.values()), None))
        if not uploaded:
            if is_ajax:
                return JsonResponse({'success': False, 'message_key': 'settings.mysql_connections.import_error',}, status=400)
            messages.error(request, 'Import file missing')
            return redirect('mysql_connections_list')

        max_size = 1 * 1024 * 1024
        try:
            if uploaded.size > max_size:
                if is_ajax:
                    return JsonResponse({'success': False, 'message_key': 'settings.mysql_connections.import_file_too_large'}, status=400)
                messages.error(request, 'Archivo demasiado grande')
                return redirect('mysql_connections_list')
        except Exception:
            pass

        try:
            raw = uploaded.read()
            data = json.loads(raw.decode('utf-8'))
        except Exception:
            if is_ajax:
                return JsonResponse({'success': False, 'message_key': 'settings.mysql_connections.import_invalid_format'}, status=400)
            messages.error(request, 'Formato inválido')
            return redirect('mysql_connections_list')

        if not isinstance(data, dict) or 'connections' not in data or not isinstance(data.get('connections'), list):
            if is_ajax:
                return JsonResponse({'success': False, 'message_key': 'settings.mysql_connections.import_invalid_format'}, status=400)
            messages.error(request, 'Formato inválido')
            return redirect('mysql_connections_list')

        conns = data.get('connections', [])
        seen = set()
        normalized = []
        import re as _re
        name_re = _re.compile(r'^[a-z0-9_]+$')
        for idx, item in enumerate(conns):
            if not isinstance(item, dict):
                if is_ajax:
                    return JsonResponse({'success': False, 'message_key': 'settings.mysql_connections.import_invalid_format'}, status=400)
                messages.error(request, 'Formato inválido')
                return redirect('mysql_connections_list')

            required = ('nombre_logico', 'host', 'port', 'user', 'password', 'db_name')
            for r in required:
                if r not in item:
                    if is_ajax:
                        return JsonResponse({'success': False, 'message_key': 'settings.mysql_connections.import_missing_fields'}, status=400)
                    messages.error(request, 'Faltan campos')
                    return redirect('mysql_connections_list')

            name = str(item.get('nombre_logico') or '').lower().strip()
            if not name_re.match(name):
                if is_ajax:
                    return JsonResponse({'success': False, 'message_key': 'settings.mysql_connections.import_invalid_name'}, status=400)
                messages.error(request, 'Nombre inválido')
                return redirect('mysql_connections_list')

            if name in seen:
                if is_ajax:
                    return JsonResponse({'success': False, 'message_key': 'settings.mysql_connections.import_duplicate_names'}, status=400)
                messages.error(request, 'Nombres duplicados en archivo')
                return redirect('mysql_connections_list')

            seen.add(name)
            try:
                port = int(item.get('port') or 3306)
            except Exception:
                port = 3306

            normalized.append({
                'nombre_logico': name,
                'host': str(item.get('host') or ''),
                'port': port,
                'user': str(item.get('user') or ''),
                'password': str(item.get('password') or ''),
                'db_name': str(item.get('db_name') or ''),
                'is_active': bool(item.get('is_active', True)),
            })

        empresa_id = request.session.get('empresa_id')
        try:
            with transaction.atomic():
                SettingsMySQLConnection.objects.filter(empresa_id=empresa_id).delete()
                for row in normalized:
                    SettingsMySQLConnection.objects.create(
                        empresa_id=empresa_id,
                        nombre_logico=row['nombre_logico'],
                        engine='django.db.backends.mysql',
                        host=row['host'],
                        port=row['port'],
                        user=row['user'],
                        password=row['password'],
                        db_name=row['db_name'],
                        is_active=row['is_active'],
                    )
        except Exception:
            if is_ajax:
                return JsonResponse({'success': False, 'message_key': 'settings.mysql_connections.import_error'}, status=500)
            messages.error(request, 'Error al importar')
            return redirect('mysql_connections_list')

        if is_ajax:
            return JsonResponse({'success': True, 'message_key': 'settings.mysql_connections.import_success'})
        messages.success(request, 'Import completed')
        return redirect('mysql_connections_list')

