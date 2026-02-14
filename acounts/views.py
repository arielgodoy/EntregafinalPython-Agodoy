from django.shortcuts import render, redirect
from .forms import AvatarForm
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import PasswordChangeForm
from django.contrib import messages
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth import authenticate, login, logout
from django.utils import timezone
from settings.models import UserPreferences
from access_control.services.empresa_activa import resolve_post_login, set_empresa_activa_en_sesion
from access_control.decorators import verificar_permiso
import time
from acounts.forms import CustomUserForm
from django.contrib.auth.decorators import user_passes_test
from django.contrib.auth import update_session_auth_hash

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
    """Editar perfil de usuario y avatar."""
    user = request.user
    avatar = user.avatar
    if request.method == 'POST':
        user_form = CustomUserForm(request.POST, instance=user)
        avatar_form = AvatarForm(request.POST, request.FILES, instance=avatar)
        if user_form.is_valid() and avatar_form.is_valid():
            user_form.save()
            avatar_form.save()
            messages.success(request, "Perfil actualizado correctamente.")
            return redirect('editar_perfil')
    else:
        user_form = CustomUserForm(instance=user)
        avatar_form = AvatarForm(instance=avatar)
    
    return render(request, 'editar_perfil.html', {
        'user_form': user_form,
        'avatar_form': avatar_form
    })



def login_view(request):
    if request.method == 'POST':
        username = request.POST['username'].lower()
        password = request.POST['password']
        user = authenticate(username=username, password=password)
        if user is not None:
            login(request, user)
            prefs, _ = UserPreferences.objects.get_or_create(user=user)
            if not prefs.fecha_sistema:
                prefs.fecha_sistema = timezone.localdate()
                prefs.save(update_fields=["fecha_sistema"])
            request.session["fecha_sistema"] = prefs.fecha_sistema.isoformat()
            status, empresa = resolve_post_login(request, user)
            if status == "ONE" and empresa:
                set_empresa_activa_en_sesion(request, empresa)
                return redirect('biblioteca:listar_propiedades')
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
    avatar = request.user.avatar    
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
    """Cambiar contraseña del usuario."""
    if request.method == 'POST':
        form = PasswordChangeForm(request.user, request.POST)
        if form.is_valid():
            user = form.save()
            update_session_auth_hash(request, user)  # 🔐 Esta línea es clave
            messages.success(request, 'Tu contraseña ha sido cambiada con éxito.')
            return redirect('editar_perfil')
        else:
            messages.error(request, 'Por favor corrige los errores abajo.')
    else:
        form = PasswordChangeForm(request.user)
    return render(request, 'cambiar_password.html', {'form': form})