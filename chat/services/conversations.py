from django.contrib.auth.models import User
from django.db.models import Count

from access_control.models import Empresa, UsuarioPerfilEmpresa
from chat.models import Conversacion


def _normalize_participants(creador_user, participant_ids):
    participants = [int(pid) for pid in (participant_ids or []) if pid]
    if creador_user and creador_user.id not in participants:
        participants.append(creador_user.id)
    return list(dict.fromkeys(participants))


def validate_participants(empresa_id, creador_user, participant_ids):
    if not empresa_id:
        raise ValueError("empresa_required")
    if not creador_user or not creador_user.is_authenticated:
        raise ValueError("invalid_creator")
    if not Empresa.objects.filter(id=empresa_id).exists():
        raise ValueError("empresa_not_found")
    if not UsuarioPerfilEmpresa.objects.filter(usuario=creador_user, empresa_id=empresa_id).exists():
        raise ValueError("creator_not_in_empresa")

    participants = _normalize_participants(creador_user, participant_ids)
    if not participants:
        return participants

    allowed_ids = set(
        UsuarioPerfilEmpresa.objects.filter(
            empresa_id=empresa_id,
            usuario_id__in=participants,
        ).values_list("usuario_id", flat=True)
    )
    if allowed_ids != set(participants):
        raise ValueError("participants_not_in_empresa")
    return participants


def create_conversation(empresa_id, creador_user, participant_ids):
    if not empresa_id:
        raise ValueError("empresa_required")
    if not creador_user or not creador_user.is_authenticated:
        raise ValueError("invalid_creator")
    if not Empresa.objects.filter(id=empresa_id).exists():
        raise ValueError("empresa_not_found")
    if not UsuarioPerfilEmpresa.objects.filter(usuario=creador_user, empresa_id=empresa_id).exists():
        raise ValueError("creator_not_in_empresa")

    participants = validate_participants(empresa_id, creador_user, participant_ids)
    if len(participants) < 2:
        raise ValueError("min_participants")

    if len(participants) == 2:
        existing = (
            Conversacion.objects.filter(empresa_id=empresa_id)
            .filter(participantes__id=participants[0])
            .filter(participantes__id=participants[1])
            .annotate(participant_count=Count("participantes"))
            .filter(participant_count=2)
            .first()
        )
        if existing:
            return existing

    conversation = Conversacion.objects.create(empresa_id=empresa_id)
    users = User.objects.filter(id__in=participants)
    conversation.participantes.set(users)
    return conversation
