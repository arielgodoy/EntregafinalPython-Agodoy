from django.shortcuts import render, redirect
from .forms import AvatarForm, AccountPasswordChangeForm
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth import authenticate, login, logout
from django.utils import timezone
from settings.models import UserPreferences
from access_control.models import Permiso
from access_control.services.empresa_activa import (
    get_user_initial_view_url,
    resolve_post_login,
    set_empresa_activa_en_sesion,
)
from access_control.decorators import verificar_permiso
import time


def _usuario_tiene_permiso(user, empresa_id, vista_nombre, permiso_requerido):
    if not empresa_id:
        return False
    return Permiso.objects.filter(
        usuario=user,
        empresa_id=empresa_id,
        vista__nombre=vista_nombre,
    ).filter(**{permiso_requerido: True}).exists()


def _process_password_change(request):
    """Valida y aplica el cambio de contraseña. Retorna (form, changed)."""
    form = AccountPasswordChangeForm(request.user, request.POST)
    if form.is_valid():
        user = form.save()
        update_session_auth_hash(request, user)
        messages.success(request, 'Tu contraseña ha sido cambiada con éxito.')
        return form, True

    messages.error(request, 'Por favor corrige los errores abajo.')
    return form, False


@verificar_permiso("Accounts - Cambiar Password", "modificar")
def _procesar_cambio_password_en_perfil(request, user, avatar):
    """Procesa el cambio de contraseña dentro de la pestaña del perfil."""
    password_form, changed = _process_password_change(request)
    if changed:
        return redirect(f"{request.path}?tab=password")

    user_form = CustomUserForm(instance=user)
    avatar_form = AvatarForm(instance=avatar)
    can_change_password = _usuario_tiene_permiso(
        request.user,
        request.session.get('empresa_id'),
        'Accounts - Cambiar Password',
        'modificar',
    )

    for field in user_form.fields.values():
        field.widget.attrs.update({'class': 'form-control'})
    for field in avatar_form.fields.values():
        field.widget.attrs.update({'class': 'form-control'})
    for field in password_form.fields.values():
        field.widget.attrs.update({'class': 'form-control'})

    return render(request, 'editar_perfil.html', {
        'user_form': user_form,
        'avatar_form': avatar_form,
        'password_form': password_form,
        'active_tab': 'password',
        'can_change_password': can_change_password,
        'password_min_length': AccountPasswordChangeForm.MIN_LENGTH,
    })
from acounts.forms import CustomUserForm
from django.contrib.auth.decorators import user_passes_test
from django.contrib.auth import update_session_auth_hash
from .models import Avatar

@user_passes_test(lambda u: u.is_superuser)
@login_required
def crear_usuario_admin(request):
    """Crear usuario admin (solo superusers)."""
    if request.method == 'POST':
        form = UserCreationForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "Usuario creado exitosamente.")
            return redirect('crear_usuario_admin')
    else:
        form = UserCreationForm()
    return render(request, 'crear_usuario_admin.html', {'form': form})
# Create your views here.

@login_required
@verificar_permiso("Accounts - Editar Perfil", "modificar")
def editar_perfil(request):
    """Editar perfil de usuario, avatar y cambio de contraseña dentro de la misma pantalla."""
    user = request.user
    avatar, _ = Avatar.objects.get_or_create(user=user)
    active_tab = request.GET.get('tab', 'personal')
    can_change_password = _usuario_tiene_permiso(
        user,
        request.session.get('empresa_id'),
        'Accounts - Cambiar Password',
        'modificar',
    )

    if request.method == 'POST':
        form_action = request.POST.get('form_action', 'profile')
        user_form = CustomUserForm(instance=user)
        avatar_form = AvatarForm(instance=avatar)
        password_form = AccountPasswordChangeForm(request.user)

        if form_action == 'password':
            return _procesar_cambio_password_en_perfil(request, user, avatar)

        active_tab = 'personal'
        user_form = CustomUserForm(request.POST, instance=user)
        avatar_form = AvatarForm(request.POST, request.FILES, instance=avatar)
        for field in user_form.fields.values():
            field.widget.attrs.update({'class': 'form-control'})
        for field in avatar_form.fields.values():
            field.widget.attrs.update({'class': 'form-control'})
        if user_form.is_valid() and avatar_form.is_valid():
            user_form.save()
            avatar_form.save()
            messages.success(request, 'Perfil actualizado correctamente.')
            return redirect('editar_perfil')
        messages.error(request, 'Revisa los datos ingresados.')
    else:
        user_form = CustomUserForm(instance=user)
        avatar_form = AvatarForm(instance=avatar)
        password_form = AccountPasswordChangeForm(request.user)

    for field in user_form.fields.values():
        field.widget.attrs.update({'class': 'form-control'})
    for field in avatar_form.fields.values():
        field.widget.attrs.update({'class': 'form-control'})
    for field in password_form.fields.values():
        field.widget.attrs.update({'class': 'form-control'})

    return render(request, 'editar_perfil.html', {
        'user_form': user_form,
        'avatar_form': avatar_form,
        'password_form': password_form,
        'active_tab': active_tab,
        'can_change_password': can_change_password,
        'password_min_length': AccountPasswordChangeForm.MIN_LENGTH,
    })



def login_view(request):
    if request.method == 'POST':
        username = request.POST['username'].lower()
        password = request.POST['password']
        user = authenticate(username=username, password=password)
        if user is not None:
            login(request, user)
            if request.POST.get('remember_me'):
                request.session.set_expiry(8 * 60 * 60)
            else:
                request.session.set_expiry(0)
            prefs, _ = UserPreferences.objects.get_or_create(user=user)
            prefs.fecha_sistema = timezone.localdate()
            prefs.save(update_fields=["fecha_sistema"])
            request.session["fecha_sistema"] = prefs.fecha_sistema.isoformat()
            status, empresa = resolve_post_login(request, user)
            request.session.pop('ultima_vista_url', None)
            if status == "ONE" and empresa:
                set_empresa_activa_en_sesion(request, empresa)
                return redirect(get_user_initial_view_url(user))
            if status == "MANY":
                return redirect('access_control:seleccionar_empresa')

            logout(request)
            return render(
                request,
                'pages/authentication/auth-signin-basic.html',
                {
                    'error_key': 'auth.login.error.no_company',
                    'error_message': 'No tienes empresas asignadas. Contacta al administrador.',
                },
            )
        else:
            # Mostrar mensaje de error si el login no es válido
            return render(
                request,
                'pages/authentication/auth-signin-basic.html',
                {
                    'error_key': 'auth.login.error.invalid',
                    'error_message': 'Nombre de usuario o contraseña incorrectos.',
                },
            )
    return render(request, 'pages/authentication/auth-signin-basic.html')

def logout_view(request):
    # Vista para realizar el logout (opcional)
    request.session.pop('ultima_vista_url', None)
    logout(request)
    return redirect('login')



def registro_usuario(request):
    if request.method == 'POST':
        form = UserCreationForm(request.POST)
        if form.is_valid():
            form.save()
            username = form.cleaned_data.get('username').lower()
            messages.success(request, f'Usuario {username} creado con éxito. Por favor, inicia sesión.')
            #time.sleep(5)
            return redirect('login')
    else:
        form = UserCreationForm()
    return render(request, 'registro_usuario.html', {'form': form})



@login_required
def subeAvatar(request):
    """Subir/cambiar avatar de usuario."""
    avatar, _ = Avatar.objects.get_or_create(user=request.user)
    if request.method == 'POST':
        form = AvatarForm(request.POST, request.FILES, instance=avatar)
        if form.is_valid():
            form.save()
            return redirect('subeavatar') 
    else:
        form = AvatarForm(instance=avatar)
    return render(request, 'upload_avatar.html', {'form': form})



@login_required
@verificar_permiso("Accounts - Cambiar Password", "modificar")
def cambiar_password(request):
    """Cambiar contraseña del usuario (URL legacy, misma política que el tab de perfil)."""
    if request.method == 'POST':
        form, changed = _process_password_change(request)
        if changed:
            return redirect('editar_perfil')
    else:
        form = AccountPasswordChangeForm(request.user)

    for field in form.fields.values():
        field.widget.attrs.update({'class': 'form-control'})

    return render(request, 'cambiar_password.html', {
        'form': form,
        'password_min_length': AccountPasswordChangeForm.MIN_LENGTH,
    })