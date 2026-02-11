import itertools
import uuid

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction

from access_control.models import Empresa, PerfilAcceso, UsuarioPerfilEmpresa
from chat.models import Conversacion, Mensaje
from chat.services.messages import create_message
from notificaciones.models import DemoSeedLog, Notification
from notificaciones.services import create_notification


class Command(BaseCommand):
    help = "Seed demo chat and notifications data for local validation."

    def add_arguments(self, parser):
        parser.add_argument("--empresa", type=int, default=None)
        parser.add_argument("--users", type=int, default=4)
        parser.add_argument("--convs", type=int, default=3)
        parser.add_argument("--msgs", type=int, default=4)
        parser.add_argument("--notifs", type=int, default=3)
        parser.add_argument("--reset", action="store_true")

    def handle(self, *args, **options):
        empresa = self._get_empresa(options.get("empresa"))
        if not empresa:
            self.stdout.write("No hay empresas disponibles. Aborta seed_demo_comms.")
            return

        if options.get("reset"):
            self._reset_demo(empresa)
            return

        users_target = max(int(options.get("users") or 0), 0)
        convs_target = max(int(options.get("convs") or 0), 0)
        msgs_target = max(int(options.get("msgs") or 0), 0)
        notifs_target = max(int(options.get("notifs") or 0), 0)

        if convs_target > 0 or msgs_target > 0:
            min_users = 2
        elif notifs_target > 0:
            min_users = 1
        else:
            min_users = 0
        if users_target < min_users:
            users_target = min_users

        created_user_ids = []
        created_userperfil_ids = []
        created_perfil_ids = []
        created_conversation_ids = []
        created_message_ids = []
        created_notification_ids = []
        created_chat_notification_keys = []

        with transaction.atomic():
            users, perfil, created_perfil = self._get_or_create_users(
                empresa, users_target
            )
            created_user_ids.extend(created_perfil["created_user_ids"])
            created_userperfil_ids.extend(created_perfil["created_userperfil_ids"])
            created_perfil_ids.extend(created_perfil["created_perfil_ids"])

            if convs_target > 0:
                conversations_data = self._create_conversations(
                    empresa, users, convs_target, msgs_target
                )
                created_conversation_ids.extend(conversations_data["conversation_ids"])
                created_message_ids.extend(conversations_data["message_ids"])
                created_chat_notification_keys.extend(conversations_data["chat_notification_keys"])

            if notifs_target > 0:
                created_notification_ids.extend(
                    self._create_notifications(empresa, users, notifs_target)
                )

            DemoSeedLog.objects.create(
                empresa=empresa,
                created_by_user=None,
                payload_json={
                    "users": created_user_ids,
                    "user_perfiles": created_userperfil_ids,
                    "perfiles": created_perfil_ids,
                    "conversations": created_conversation_ids,
                    "messages": created_message_ids,
                    "notifications": created_notification_ids,
                    "chat_notification_keys": created_chat_notification_keys,
                },
            )

        self._print_summary(
            empresa,
            users,
            created_user_ids,
            created_conversation_ids,
            created_message_ids,
            created_notification_ids,
            notifs_target,
        )

    def _get_empresa(self, empresa_id):
        if empresa_id:
            return Empresa.objects.filter(id=empresa_id).first()
        return Empresa.objects.order_by("id").first()

    def _get_or_create_users(self, empresa, users_target):
        assignments = (
            UsuarioPerfilEmpresa.objects.filter(empresa=empresa)
            .select_related("usuario")
            .order_by("id")
        )
        users = [item.usuario for item in assignments]
        created_user_ids = []
        created_userperfil_ids = []
        created_perfil_ids = []

        if len(users) >= users_target:
            return users[:users_target], None, {
                "created_user_ids": created_user_ids,
                "created_userperfil_ids": created_userperfil_ids,
                "created_perfil_ids": created_perfil_ids,
            }

        perfil = PerfilAcceso.objects.order_by("id").first()
        if not perfil:
            perfil = PerfilAcceso.objects.create(nombre="Demo", descripcion="Demo")
            created_perfil_ids.append(perfil.id)

        user_model = get_user_model()
        start_index = len(users) + 1
        for idx in range(start_index, users_target + 1):
            username = f"user_demo_{idx}"
            email = f"user_demo_{idx}@demo.local"
            user = user_model.objects.create_user(username=username, email=email, password="demo12345")
            created_user_ids.append(user.id)
            assignment = UsuarioPerfilEmpresa.objects.create(
                usuario=user,
                empresa=empresa,
                perfil=perfil,
                asignado_por=None,
            )
            created_userperfil_ids.append(assignment.id)
            users.append(user)

        return users, perfil, {
            "created_user_ids": created_user_ids,
            "created_userperfil_ids": created_userperfil_ids,
            "created_perfil_ids": created_perfil_ids,
        }

    def _create_conversations(self, empresa, users, convs_target, msgs_target):
        conversation_ids = []
        message_ids = []
        chat_notification_keys = []

        pairs = list(itertools.combinations(users, 2))
        if not pairs:
            return {
                "conversation_ids": conversation_ids,
                "message_ids": message_ids,
                "chat_notification_keys": chat_notification_keys,
            }

        pair_cycle = itertools.cycle(pairs)
        for _ in range(convs_target):
            user_a, user_b = next(pair_cycle)
            conversation = Conversacion.objects.create(empresa=empresa)
            conversation.participantes.add(user_a, user_b)
            conversation_ids.append(conversation.id)

            for idx in range(msgs_target):
                sender = user_a if idx % 2 == 0 else user_b
                mensaje = create_message(
                    conversation,
                    sender,
                    f"Demo mensaje {idx + 1} en conversacion {conversation.id}",
                    empresa_id=empresa.id,
                )
                message_ids.append(mensaje.id)
                other = user_b if sender.id == user_a.id else user_a
                chat_notification_keys.append(f"chat:msg:{mensaje.id}:to:{other.id}")

        return {
            "conversation_ids": conversation_ids,
            "message_ids": message_ids,
            "chat_notification_keys": chat_notification_keys,
        }

    def _create_notifications(self, empresa, users, notifs_target):
        created_notification_ids = []
        if not users:
            return created_notification_ids

        tipos = [Notification.Tipo.ALERT, Notification.Tipo.SYSTEM]
        for idx in range(notifs_target):
            user = users[idx % len(users)]
            tipo = tipos[idx % len(tipos)]
            dedupe_key = f"demo:notif:{uuid.uuid4().hex}"
            notification = create_notification(
                destinatario=user,
                empresa=empresa,
                tipo=tipo,
                titulo=f"Demo {tipo} {idx + 1}",
                cuerpo="Notificacion demo generada por seed_demo_comms.",
                url="/",
                actor=None,
                dedupe_key=dedupe_key,
            )
            created_notification_ids.append(notification.id)

        return created_notification_ids

    def _reset_demo(self, empresa):
        logs = DemoSeedLog.objects.filter(empresa=empresa).order_by("-created_at")
        if not logs.exists():
            self.stdout.write("No hay datos demo para borrar.")
            return

        deleted_notifications = 0
        deleted_conversations = 0
        deleted_messages = 0
        deleted_users = 0
        deleted_userperfil = 0
        deleted_perfiles = 0

        for log in logs:
            payload = log.payload_json or {}
            notification_ids = payload.get("notifications", [])
            chat_keys = payload.get("chat_notification_keys", [])
            message_ids = payload.get("messages", [])
            conversation_ids = payload.get("conversations", [])
            userperfil_ids = payload.get("user_perfiles", [])
            user_ids = payload.get("users", [])
            perfil_ids = payload.get("perfiles", [])

            if notification_ids:
                deleted_notifications += Notification.objects.filter(id__in=notification_ids).delete()[0]
            if chat_keys:
                deleted_notifications += Notification.objects.filter(dedupe_key__in=chat_keys).delete()[0]
            if message_ids:
                deleted_messages += Mensaje.objects.filter(id__in=message_ids).delete()[0]
            if conversation_ids:
                deleted_conversations += Conversacion.objects.filter(id__in=conversation_ids).delete()[0]
            if userperfil_ids:
                deleted_userperfil += UsuarioPerfilEmpresa.objects.filter(id__in=userperfil_ids).delete()[0]
            if user_ids:
                user_model = get_user_model()
                for user_id in user_ids:
                    if not UsuarioPerfilEmpresa.objects.filter(usuario_id=user_id).exists():
                        deleted_users += user_model.objects.filter(id=user_id).delete()[0]
            if perfil_ids:
                for perfil_id in perfil_ids:
                    if not UsuarioPerfilEmpresa.objects.filter(perfil_id=perfil_id).exists():
                        deleted_perfiles += PerfilAcceso.objects.filter(id=perfil_id).delete()[0]

            log.delete()

        self.stdout.write(
            "Reset demo completado. "
            f"Notifications: {deleted_notifications}, "
            f"Mensajes: {deleted_messages}, "
            f"Conversaciones: {deleted_conversations}, "
            f"UsuarioPerfilEmpresa: {deleted_userperfil}, "
            f"Usuarios: {deleted_users}, "
            f"Perfiles: {deleted_perfiles}."
        )

    def _print_summary(
        self,
        empresa,
        users,
        created_user_ids,
        created_conversation_ids,
        created_message_ids,
        created_notification_ids,
        notifs_target,
    ):
        self.stdout.write(
            f"Empresa usada: {empresa.id} - {empresa.descripcion or empresa.codigo}"
        )
        if users:
            self.stdout.write(
                "Usuarios usados: " + ", ".join([u.email or u.username for u in users])
            )
        else:
            self.stdout.write("Usuarios usados: ninguno")
        if created_user_ids:
            self.stdout.write(
                "Se crearon usuarios demo con password demo12345."
            )
        self.stdout.write(
            f"Conversaciones creadas: {len(created_conversation_ids)}"
        )
        self.stdout.write(
            f"Mensajes creados: {len(created_message_ids)}"
        )
        self.stdout.write(
            f"Notificaciones demo creadas: {len(created_notification_ids)}"
        )
        self.stdout.write(
            f"Notificaciones por mensajes (MESSAGE) generadas via create_message: {len(created_message_ids)}"
        )
