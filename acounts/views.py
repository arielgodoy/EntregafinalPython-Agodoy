from django.shortcuts import render,redirect
from .forms  import AvatarForm
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import PasswordChangeForm
from django.contrib import messages
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth import authenticate, login,logout
import time
from acounts.forms import CustomUserForm
from django.contrib.auth.decorators import user_passes_test
from django.contrib.auth import update_session_auth_hash
#from django.contrib.auth.forms import UserCreationForm

@user_passes_test(lambda u: u.is_superuser)
def crear_usuario_admin(request):
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
def editar_perfil(request):
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
            return redirect('biblioteca:listar_propiedades')  # Redirigir al usuario a la página de inicio después de un login exitoso cambair a dashboard de aplicaciones
        else:
            # Mostrar mensaje de error si el login no es válido
            error_message = "Nombre de usuario o contraseña incorrectos."
            return render(request, 'pages/authentication/auth-signin-basic.html', {'error_message': error_message})
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



def subeAvatar(request):    
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
def cambiar_password(request):
    if request.method == 'POST':
        print(request.POST) 
        form = PasswordChangeForm(request.user, request.POST)
        if form.is_valid():
            user = form.save()
            update_session_auth_hash(request, user)  # 🔐 Esta línea es la clave
            messages.success(request, 'Tu contraseña ha sido cambiada con éxito.')
            return redirect('editar_perfil')  # O donde desees redirigir
        else:
            print("Errores del formulario:", form.errors)
            messages.error(request, 'Por favor corrige los errores abajo.')
    else:
        form = PasswordChangeForm(request.user)
    return render(request, 'cambiar_password.html', {'form': form})