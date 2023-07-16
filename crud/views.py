from django.shortcuts import render, redirect,get_object_or_404
from .models import Documento,Propiedades,Propietario,Avatar,Conversacion
from .forms import DocForm,BuscaDocs,PropForm,BuscaProps,PropietarioForm,BuscaPropietario,UserRegisterForm,UserEditform,AvatarForm, MensajeForm
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth import login,authenticate
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.views import View
from django.shortcuts import render
from django.urls import reverse_lazy
from django.http import HttpResponse, HttpResponseRedirect
from django.contrib.auth.models import User
from .forms import MensajeForm,ConversacionForm




#################################################################
#                                                               #
# clases basadas en vistas "protegidas" por LoginRequiredMixin  #
#                                                               #
#################################################################

class ListarPropietariosView(LoginRequiredMixin,View):
    def get(self, request):
        form = BuscaPropietario(request.GET)
        if form.is_valid():
            filtro = form.cleaned_data['nombre']
            propietarios = Propietario.objects.filter(nombre__icontains=filtro)
        else:
            print("No es válido")
        return render(request, "listapropietarios.html", {'form': form, 'propietarios': propietarios})

class ListarDocsView(LoginRequiredMixin,View):
    def get(self, request):
        form = BuscaDocs(request.GET)
        if form.is_valid():
            filtro = form.cleaned_data['titulo']
            docs = Documento.objects.filter(titulo__icontains=filtro)
        else:
            print("No es válido")
        return render(request, "listadocs.html", {'form': form, 'docs': docs})

class ListarPropiedadesView(LoginRequiredMixin,View):
    def get(self, request):
        form = BuscaProps(request.GET)
        if form.is_valid():
            filtro = form.cleaned_data['rol']
            props = Propiedades.objects.filter(rol__icontains=filtro)
        else:
            print("No es válido")
        return render(request, "listapropiedades.html", {'form': form, 'props': props})


#################################################################
#                                                               #
# Vistas Comunes  "protegidas" por decorador @login_required    #
#                                                               #
#################################################################

@login_required
def inicio(request):       
    return render(request,"base.html")  

@login_required
def creaDocs(request):  
    if request.method == "POST":  
        form = DocForm(request.POST)  
        if form.is_valid():  
            try:  
                if form.save():
                    print("todo ok 2")
                model = form.instance        

                return redirect('listarDocs')  
            except:  
                pass  
    else:  
        form = DocForm()  
    return render(request,'creadoc.html',{'form':form})  

@login_required
def creaPropiedades(request):  
    if request.method == "POST":  
        form = PropForm(request.POST)  
        if form.is_valid():  
            try:  
                if form.save():
                    print("todo ok 2")
                model = form.instance       

                return redirect('listarPropiedades')  
            except:  
                pass  
    else:  
        form = PropForm()  
    return render(request,'creaPropiedad.html',{'form':form}) 

@login_required
def creaPropietario(request):  
    if request.method == "POST":  
        form = PropietarioForm(request.POST)  
        if form.is_valid():  
            try:  
                if form.save():
                    print("todo ok 2")
                model = form.instance       

                return redirect('listarPropietarios')  
            except:  
                pass  
    else:  
        form = PropietarioForm()  
    return render(request,'creaPropietario.html',{'form':form})  


@login_required
def updateDocs(request, id):  
    doc = Documento.objects.get(id=id)
    form = DocForm(initial={'titulo': doc.titulo, 'descripcion': doc.descripcion, 'autor': doc.autor, 'anio': doc.anio})
    if request.method == "POST":  
        form = DocForm(request.POST, instance=doc)  
        if form.is_valid():  
            try:  
                form.save() 
                model = form.instance
                return redirect('listarDocs')  
            except Exception as e: 
                pass    
    return render(request,'docupdate.html',{'form':form})  


@login_required
def updatePropiedades(request, id):  
    prop = Propiedades.objects.get(id=id)
    form = PropForm(initial={'rol': prop.rol, 'direccion': prop.direccion, 'rut': prop.rut})
    if request.method == "POST":  
        form = PropForm(request.POST, instance=prop)  
        if form.is_valid():  
            try:  
                form.save() 
                model = form.instance
                return redirect('listarPropiedades')  
            except Exception as e: 
                pass    
    return render(request,'propiedadupdate.html',{'form':form})  

@login_required
def updatePropietario(request, id):  
    propietario = Propietario.objects.get(id=id)
    form = PropietarioForm(initial={'nombre': propietario.nombre, 'direccion': propietario.direccion, 'fono': propietario.fono})
    if request.method == "POST":  
        form = PropietarioForm(request.POST, instance=propietario)  
        if form.is_valid():  
            try:  
                form.save() 
                model = form.instance
                return redirect('listarPropietarios')  
            except Exception as e: 
                pass    
    return render(request,'propietarioupdate.html',{'form':form})  

@login_required
def deleteDocs(request, id):
    doc = Documento.objects.get(id=id)
    try:
        doc.delete()
    except:
        pass
    return redirect('listarDocs')


@login_required
def deletePropiedades(request, id):
    prop = Propiedades.objects.get(id=id)
    try:
        prop.delete()
    except:
        pass
    return redirect('listarPropiedades')

@login_required
def deletePropietario(request, id):
    propietario = Propietario.objects.get(id=id)
    try:
        propietario.delete()
    except:
        pass
    return redirect('listarPropietarios')





def login_request(request):
    if request.method == "POST":
        form = AuthenticationForm(request, data=request.POST)
        if form.is_valid():
            usuario = form.cleaned_data.get('username')
            contra = form.cleaned_data.get('password')
            user = authenticate(username=usuario, password=contra)
            if user is not None:
                login(request, user)
                Avatar.objects.get_or_create(user=user)
                return redirect("inicio")
            else:
                mensaje = "Error, datos incorrectos"
        else:
            mensaje = "Error, formulario erróneo"
    else:
        form = AuthenticationForm()
        mensaje = "Ingrese sus credenciales"    
    return render(request, "login.html", {'form': form, "mensaje": mensaje})

@login_required
def editarUsuario(request):
    usuario = request.user
    infoavatar=request.user.avatar.imagen  
    if request.method == 'POST':
        miformulario = UserEditform(request.POST,instance=request.user)
        if miformulario.is_valid():            
            usuario.email = miformulario.cleaned_data['email']
            usuario.first_name = miformulario.cleaned_data['first_name']
            usuario.last_name = miformulario.cleaned_data['last_name'] 
            usuario.password1 = miformulario.cleaned_data['password1']
            usuario.password2 = miformulario.cleaned_data['password2']
            usuario.set_password(usuario.password2)
            avatar=miformulario.cleaned_data['avatar']            
            if avatar:
                infoavatar.avatar = avatar
                infoavatar.save()
            usuario.save()
            
            return render(request,"editar_usuario.html",{"miformulario":miformulario,"usuario":usuario})
    else:
        miformulario = UserEditform(initial={'avatar':request.user.avatar.imagen},instance=request.user)
    return render(request,"editar_usuario.html",{"miformulario":miformulario,"usuario":usuario})

def register(request):
    if request.method == 'POST':        
        form = UserRegisterForm(request.POST)
        if form.is_valid():
            username = form.cleaned_data['username']
            form.save()
            form = UserRegisterForm(request.POST)            
            success_url = reverse_lazy("login")
            return HttpResponseRedirect(success_url)
    else:        
        form = UserRegisterForm()
    
    return render(request, "registro.html", {"form": form})

def subeAvatar(request):
    avatar = request.user.avatar
    if request.method == 'POST':
        form = AvatarForm(request.POST, request.FILES, instance=avatar)
        if form.is_valid():
            form.save()
            return redirect('inicio') 
    else:
        form = AvatarForm(instance=avatar)
    return render(request, 'upload_avatar.html', {'form': form})




@login_required
def lista_conversaciones(request):
    conversaciones = Conversacion.objects.filter(participantes=request.user)
    return render(request, 'lista_conversaciones.html', {'conversaciones': conversaciones})

@login_required
def detalle_conversacion(request, conversacion_id):
    conversacion = get_object_or_404(Conversacion, id=conversacion_id, participantes=request.user)
    return render(request, 'detalle_conversacion.html', {'conversacion': conversacion})


@login_required
def enviar_mensaje(request, conversacion_id):
    conversacion = get_object_or_404(Conversacion, id=conversacion_id, participantes=request.user)
    form = MensajeForm(request.POST or None)
    
    if request.method == 'POST' and form.is_valid():
        mensaje = form.save(commit=False)
        mensaje.conversacion = conversacion
        mensaje.remitente = request.user
        mensaje.save()
        return redirect('detalle_conversacion', conversacion_id=conversacion_id)

    return render(request, 'enviar_mensaje.html', {'conversacion': conversacion, 'form': form})

@login_required
def crear_conversacion(request):
    form = ConversacionForm(request.POST or None, user=request.user)
    
    if request.method == 'POST' and form.is_valid():
        conversacion = form.save()
        return redirect('detalle_conversacion', conversacion_id=conversacion.id)

    return render(request, 'crear_conversacion.html', {'form': form})