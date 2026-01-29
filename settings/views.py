from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect
from .models import UserPreferences, ThemePreferences
from django.contrib import messages
from django import forms


#importaciones para prueba de envio de correo
import imaplib
import poplib
import smtplib
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from email.utils import formatdate, make_msgid
import json
from access_control.decorators import verificar_permiso


@csrf_exempt
@require_POST
def probar_configuracion_entrada(request):
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

@csrf_exempt
@require_POST
def probar_configuracion_salida(request):
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
        
from email.message import EmailMessage
from email.utils import formatdate, make_msgid
from django.http import JsonResponse
import mimetypes
import smtplib
import os

@csrf_exempt
@require_POST
@login_required
def enviar_correo_prueba(request):
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


from email.parser import BytesParser
from email.policy import default

@csrf_exempt
@require_POST
@login_required
def recibir_correo_prueba(request):
    try:
        prefs = UserPreferences.objects.get(user=request.user)
        if not prefs.email_host or not prefs.email_username or not prefs.email_password:
            return JsonResponse({"success": False, "error": "Configuración de correo de entrada incompleta."})

        protocolo = prefs.email_protocol
        if protocolo == "IMAP":
            # No lo implementamos aquí aún
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



#hasta aqui las importaciones para prueba de envio de correo

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

@login_required
def configurar_email(request):
    preferencias, _ = UserPreferences.objects.get_or_create(user=request.user)
    if request.method == 'POST':
        form = EmailSettingsForm(request.POST, instance=preferencias)
        if form.is_valid():
            form.save()
            messages.success(request, "Preferencias de correo guardadas correctamente.")
            return redirect('configurar_email')
    else:
        form = EmailSettingsForm(instance=preferencias)
    return render(request, 'configurar_email.html', {'form': form})


@login_required
@require_POST
@verificar_permiso("preferencias_tema", "modificar")
def guardar_preferencias(request):
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
