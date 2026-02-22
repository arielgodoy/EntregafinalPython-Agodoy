from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from django.contrib.auth import get_user_model
from .models import Conversacion, Mensaje
import json
import logging


logger = logging.getLogger(__name__)


User = get_user_model()


class ChatConsumer(AsyncWebsocketConsumer):
    """Consumer Paso 2: valida multiempresa y participación sin usar session.

    Reglas aplicadas:
    - No se usa session para empresa en WS; la empresa se valida leyendo la
      `Conversacion.empresa` y comprobando que el usuario es participante.
    - El usuario debe estar autenticado (AuthMiddlewareStack must be enabled).
    - Mensajes entrantes se guardan en DB (Mensaje) y se difunden al grupo.
    """

    async def connect(self):
        try:
            user = self.scope.get('user')
            if not user or not user.is_authenticated:
                logger.warning("chat.ws.connect denied user=%s conv_id=%s", getattr(user, 'id', None), None)
                await self.close()
                return

            # conversation_id viene desde routing URL (chat/routing.py)
            conversation_id = self.scope.get('url_route', {}).get('kwargs', {}).get('conversation_id')
            # Validar que sea entero
            try:
                conversation_id = int(conversation_id)
            except Exception:
                await self.close()
                return

            # Validar existencia y que el usuario participa en la conversación
            conversation = await database_sync_to_async(self._get_conversation)(conversation_id)
            if conversation is None or not getattr(conversation, 'empresa_id', None):
                logger.warning("chat.ws.connect denied user=%s conv_id=%s", getattr(user, 'id', None), conversation_id)
                await self.close()
                return

            is_participant = await database_sync_to_async(self._is_participant)(conversation, user.id)
            if not is_participant:
                logger.warning("chat.ws.connect denied user=%s conv_id=%s", getattr(user, 'id', None), conversation_id)
                await self.close()
                return

            # Guardar estado y unirse al grupo. Incluir empresa_id en el nombre de grupo.
            self.conversation_id = int(conversation_id)
            self.empresa_id = int(conversation.empresa_id)
            self.group_name = f'chat_empresa_{self.empresa_id}conv{self.conversation_id}'
            await self.channel_layer.group_add(self.group_name, self.channel_name)
            logger.info("chat.ws.connect ok user_id=%s conv_id=%s", self.scope.get('user').id, self.conversation_id)
            await self.accept()
        except Exception:
            # Nunca propagar excepciones al servidor ASGI
            try:
                await self.close()
            except Exception:
                pass

    async def disconnect(self, close_code):
        try:
            await self.channel_layer.group_discard(self.group_name, self.channel_name)
        except Exception:
            pass

    async def receive(self, text_data=None, bytes_data=None):
        # Aceptar sólo JSON con formato: {"type": "message", "content": "texto..."}
        if not text_data:
            return
        try:
            data = json.loads(text_data)
        except Exception:
            await self.send(text_data=json.dumps({'error': 'invalid_json'}))
            return

        if data.get('type') != 'message':
            # Ignorar otros tipos por ahora
            return

        logger.info("chat.ws.receive user_id=%s conv_id=%s keys=%s", self.scope.get('user').id, getattr(self, 'conversation_id', None), list(data.keys()))

        content = data.get('content')
        if not content or not isinstance(content, str) or not content.strip():
            await self.send(text_data=json.dumps({'error': 'empty_message'}))
            return

        # Enforce max length
        MAX_LENGTH = 2000
        content = content.strip()
        if len(content) > MAX_LENGTH:
            await self.send(text_data=json.dumps({'error': 'message_too_long'}))
            return

        # Revalidar conversation and participant antes de guardar
        conversation = await database_sync_to_async(self._get_conversation)(self.conversation_id)
        if conversation is None:
            await self.send(text_data=json.dumps({'error': 'conversation_not_found'}))
            return

        user = self.scope.get('user')
        is_participant = await database_sync_to_async(self._is_participant)(conversation, user.id)
        if not is_participant:
            await self.send(text_data=json.dumps({'error': 'not_participant'}))
            return

        # Guardar mensaje (nunca confiar en empresa enviada por cliente)
        logger.info("chat.ws.persist user_id=%s conv_id=%s content_len=%s", self.scope.get('user').id, self.conversation_id, len(content or ""))
        mensaje_obj = await database_sync_to_async(self._create_message)(conversation, user, content)

        payload = {
            'message_id': mensaje_obj.id,
            'conversation_id': self.conversation_id,
            'sender_username': getattr(user, 'username', str(user)),
            'content': mensaje_obj.contenido,
            'fecha_creacion': mensaje_obj.fecha_creacion.isoformat(),
        }

        # Difundir al grupo
        logger.info("chat.ws.broadcast user_id=%s conv_id=%s", self.scope.get('user').id, self.conversation_id)
        await self.channel_layer.group_send(self.group_name, {
            'type': 'chat.message',
            'payload': payload,
        })

    async def chat_message(self, event):
        payload = event.get('payload')
        if payload:
            try:
                logger.info("chat.ws.send_to_client conv_id=%s payload_keys=%s", getattr(self, 'conversation_id', None), list(payload.keys()))
            except Exception:
                pass
            await self.send(text_data=json.dumps(payload))

    # Helper sync DB methods
    def _get_conversation(self, conversation_id):
        try:
            return Conversacion.objects.select_related('empresa').prefetch_related('participantes').get(id=conversation_id)
        except Conversacion.DoesNotExist:
            return None

    def _is_participant(self, conversation, user_id):
        return conversation.participantes.filter(id=user_id).exists()

    def _create_message(self, conversation, user, text):
        return Mensaje.objects.create(conversacion=conversation, remitente=user, contenido=text)
