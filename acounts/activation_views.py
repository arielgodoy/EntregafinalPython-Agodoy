import hashlib

from django.shortcuts import redirect, render
from django.utils import timezone

from acounts.forms import ActivationPasswordForm
from acounts.models import UserEmailToken, UserEmailTokenPurpose
from acounts.services.tokens import validate_and_use_token


def _hash_token(token_plain: str) -> str:
    return hashlib.sha256(token_plain.encode('utf-8')).hexdigest()


def _get_valid_user_for_token(token_plain, purpose):
    token_hash = _hash_token(token_plain)
    now = timezone.now()
    token_obj = UserEmailToken.objects.filter(
        token_hash=token_hash,
        purpose=purpose,
        used_at__isnull=True,
        expires_at__gt=now,
    ).select_related('user').first()

    return token_obj.user if token_obj else None


def activate_account(request, token):
    user = _get_valid_user_for_token(token, UserEmailTokenPurpose.ACTIVATE)
    if not user:
        return render(request, 'acounts/activation_invalid.html', status=400)

    if request.method == 'POST':
        form = ActivationPasswordForm(request.POST)
        if form.is_valid():
            activated_user = validate_and_use_token(token, UserEmailTokenPurpose.ACTIVATE)
            if not activated_user:
                return render(request, 'acounts/activation_invalid.html', status=400)

            form.save(activated_user)
            activated_user.is_active = True
            activated_user.save(update_fields=['is_active'])
            return redirect('login')
    else:
        form = ActivationPasswordForm()

    return render(request, 'acounts/activation_form.html', {'form': form})
