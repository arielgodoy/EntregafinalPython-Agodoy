import os
import asyncio
import json
import uuid
import pytest

# Inicializar Django para que AppRegistry esté listo antes de importar ASGI
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'AppDocs.settings_test')
import django
django.setup()

from django.contrib.auth import get_user_model
from django.contrib.auth import BACKEND_SESSION_KEY, SESSION_KEY
from django.contrib.sessions.backends.db import SessionStore
from channels.testing import WebsocketCommunicator, ApplicationCommunicator
from AppDocs.asgi import application
from chat.consumers import ChatConsumer
from chat.models import Conversacion, Mensaje
from access_control.models import Empresa
from asgiref.sync import sync_to_async

User = get_user_model()

@pytest.mark.asyncio
async def test_connect_unauthenticated(db):
    communicator = WebsocketCommunicator(application, "/ws/chat/1/")
    connected, _ = await communicator.connect()
    assert not connected
    await communicator.disconnect()

@pytest.mark.asyncio
async def test_connect_authenticated_not_participant(db):
    # Crear empresa, usuario y conversación sin el usuario (usando sync_to_async)
    empresa = await sync_to_async(Empresa.objects.create, thread_sensitive=True)(codigo='01', descripcion='E1')
    other_username = f"other_{uuid.uuid4().hex[:8]}"
    ariel_username = f"ariel_{uuid.uuid4().hex[:8]}"
    other = await sync_to_async(User.objects.create_user, thread_sensitive=True)(username=other_username, password='x')
    ariel = await sync_to_async(User.objects.create_user, thread_sensitive=True)(username=ariel_username, password='x')

    conv = await sync_to_async(Conversacion.objects.create, thread_sensitive=True)(empresa=empresa)
    await sync_to_async(conv.participantes.add, thread_sensitive=True)(other)

    # Crear sesión para 'ariel' (sincronizando)
    session = await sync_to_async(SessionStore, thread_sensitive=True)()
    session[SESSION_KEY] = ariel.pk
    session[BACKEND_SESSION_KEY] = 'django.contrib.auth.backends.ModelBackend'
    await sync_to_async(session.save, thread_sensitive=True)()
    cookie = f'sessionid={session.session_key}'

    communicator = WebsocketCommunicator(application, f"/ws/chat/{conv.id}/", headers=[(b'cookie', cookie.encode())])
    connected, _ = await communicator.connect()
    assert not connected
    await communicator.disconnect()

@pytest.mark.asyncio
async def test_participant_send_and_receive(db):
    empresa = await sync_to_async(Empresa.objects.create, thread_sensitive=True)(codigo='02', descripcion='E2')
    ariel_username = f"ariel_{uuid.uuid4().hex[:8]}"
    ariel = await sync_to_async(User.objects.create_user, thread_sensitive=True)(username=ariel_username, password='x')
    conv = await sync_to_async(Conversacion.objects.create, thread_sensitive=True)(empresa=empresa)
    await sync_to_async(conv.participantes.add, thread_sensitive=True)(ariel)

    # session for ariel
    session = await sync_to_async(SessionStore, thread_sensitive=True)()
    session[SESSION_KEY] = ariel.pk
    session[BACKEND_SESSION_KEY] = 'django.contrib.auth.backends.ModelBackend'
    await sync_to_async(session.save, thread_sensitive=True)()
    cookie = f'sessionid={session.session_key}'

    # Use ApplicationCommunicator to inject `user` into scope (avoid session cookie fragility)
    app = ChatConsumer.as_asgi()
    scope = {
        'type': 'websocket',
        'path': f"/ws/chat/{conv.id}/",
        'headers': [],
        'client': ('testclient', 1234),
        'server': ('testserver', 80),
        'scheme': 'ws',
        'http_version': '1.1',
        'user': ariel,
        'url_route': {'kwargs': {'conversation_id': conv.id}},
    }

    communicator = ApplicationCommunicator(app, scope)
    # Initiate WebSocket connection
    await communicator.send_input({'type': 'websocket.connect'})
    accept = await communicator.receive_output()
    assert accept['type'] == 'websocket.accept'

    # Send message
    await communicator.send_input({'type': 'websocket.receive', 'text': json.dumps({'type': 'message', 'content': 'hola desde prueba'})})

    # Receive broadcast (chat_message)
    out = await communicator.receive_output()
    payload = out.get('text')
    assert payload is not None
    data = json.loads(payload)
    assert data.get('conversation_id') == conv.id
    assert data.get('content') == 'hola desde prueba'

    # Verificar DB (usar sync_to_async)
    m = await sync_to_async(lambda: Mensaje.objects.filter(conversacion=conv, remitente=ariel, contenido='hola desde prueba').first(), thread_sensitive=True)()
    assert m is not None

    # Close (incluir código para evitar KeyError en websocket.disconnect)
    await communicator.send_input({'type': 'websocket.disconnect', 'code': 1000})
    await communicator.wait()
