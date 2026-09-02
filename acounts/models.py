from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone

try:
    JSONField = models.JSONField
except AttributeError:
    JSONField = models.TextField

from django.contrib.auth.models import AbstractUser, Group, Permission
from django.db.models.signals import post_save
from django.dispatch import receiver
from settings.models import UserPreferences
from access_control.models import Empresa





class Avatar(models.Model):
    user = models.OneToOneField(User,on_delete=models.CASCADE,null=True)
    imagen = models.ImageField(default='avatares/default.jpg',upload_to='avatares',null = True, blank=True)    
    profesion = models.CharField(max_length=100,default='')
    dni = models.CharField(max_length=20,default='')   
    def __str__(self):
        return f'{self.user} {self.imagen}'


class UserActiveSession(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='active_session')
    session_key = models.CharField(max_length=40, unique=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return str(self.user)


class EmailAccount(models.Model):
    name = models.CharField(max_length=100, unique=True)
    from_email = models.EmailField()
    from_name = models.CharField(max_length=150)
    smtp_host = models.CharField(max_length=255)
    smtp_port = models.PositiveIntegerField()
    smtp_user = models.CharField(max_length=255)
    smtp_password = models.CharField(max_length=255)
    use_tls = models.BooleanField(default=False)
    use_ssl = models.BooleanField(default=False)
    reply_to = models.EmailField(blank=True, null=True)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return f"{self.name} ({self.from_email})"


class SystemConfig(models.Model):
    is_active = models.BooleanField(default=False)
    active_slot = models.CharField(
        max_length=32,
        unique=True,
        null=True,
        blank=True,
        editable=False,
    )
    public_base_url = models.URLField()
    default_from_email = models.EmailField()
    default_from_name = models.CharField(max_length=150)

    security_email_account = models.ForeignKey(
        EmailAccount,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='system_security_configs'
    )
    notifications_email_account = models.ForeignKey(
        EmailAccount,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='system_notifications_configs'
    )
    alerts_email_account = models.ForeignKey(
        EmailAccount,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='system_alerts_configs'
    )

    activation_ttl_hours = models.PositiveIntegerField(default=24)
    reset_ttl_minutes = models.PositiveIntegerField(default=90)
    max_failed_logins = models.PositiveIntegerField(default=5)
    lock_minutes = models.PositiveIntegerField(default=15)

    def save(self, *args, **kwargs):
        from django.db import IntegrityError, transaction

        self.active_slot = 'SYSTEM_CONFIG_ACTIVE' if self.is_active else None
        using = kwargs.get('using') or self._state.db or 'default'
        update_fields = kwargs.get('update_fields')
        if update_fields is not None:
            kwargs['update_fields'] = set(update_fields) | {'active_slot', 'is_active'}

        for attempt in range(2):
            try:
                with transaction.atomic(using=using):
                    if self.is_active:
                        # QuerySet.update() bypasses save(), so update both fields here.
                        type(self).objects.using(using).exclude(pk=self.pk).update(
                            is_active=False,
                            active_slot=None,
                        )
                    if self.active_slot not in (None, 'SYSTEM_CONFIG_ACTIVE'):
                        self.active_slot = None
                    return super().save(*args, **kwargs)
            except IntegrityError:
                if attempt == 1:
                    raise

    def __str__(self):
        return f"SystemConfig ({'active' if self.is_active else 'inactive'})"


class CompanyConfig(models.Model):
    empresa = models.OneToOneField(Empresa, on_delete=models.CASCADE)
    public_base_url = models.URLField(blank=True, null=True)
    from_name = models.CharField(max_length=150, blank=True, null=True)
    from_email = models.EmailField(blank=True, null=True)

    security_email_account = models.ForeignKey(
        EmailAccount,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='company_security_configs'
    )
    notifications_email_account = models.ForeignKey(
        EmailAccount,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='company_notifications_configs'
    )
    alerts_email_account = models.ForeignKey(
        EmailAccount,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='company_alerts_configs'
    )

    activation_ttl_hours = models.PositiveIntegerField(blank=True, null=True)
    reset_ttl_minutes = models.PositiveIntegerField(blank=True, null=True)
    max_failed_logins = models.PositiveIntegerField(blank=True, null=True)
    lock_minutes = models.PositiveIntegerField(blank=True, null=True)

    def __str__(self):
        return f"CompanyConfig ({self.empresa.codigo})"


if hasattr(models, 'TextChoices'):
    class UserEmailTokenPurpose(models.TextChoices):
        ACTIVATE = 'ACTIVATE', 'ACTIVATE'
else:
    class UserEmailTokenPurpose:
        ACTIVATE = 'ACTIVATE'
        choices = [(ACTIVATE, 'ACTIVATE')]


class UserEmailToken(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='email_tokens')
    purpose = models.CharField(max_length=20, choices=UserEmailTokenPurpose.choices)
    token_hash = models.CharField(max_length=64, unique=True)
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='created_email_tokens'
    )
    meta = JSONField(blank=True, null=True)

    class Meta:
        indexes = [
            models.Index(fields=['user', 'purpose']),
        ]

    def is_expired(self):
        return timezone.now() >= self.expires_at

    def is_used(self):
        return self.used_at is not None
    
@receiver(post_save, sender=User)
def create_user_avatar(sender, instance, created, **kwargs):
    if created:
        Avatar.objects.create(user=instance)
        UserPreferences.objects.create(user=instance)

    

