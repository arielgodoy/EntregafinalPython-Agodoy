from django.db import models
from django.contrib.auth.models import User
from access_control.models import Empresa

class UserPreferences(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)

    # 🖥️ Opciones para layout según layout.js
    LAYOUT_CHOICES = [
        ("vertical", "Vertical"),
        ("horizontal", "Horizontal"),
        ("twocolumn", "Two Column"),
        ("semibox", "Semi Boxed"),
    ]

    THEME_CHOICES = [
        ("light", "Claro"),
        ("dark", "Oscuro"),
    ]

    SIDEBAR_VISIBILITY_CHOICES = [
        ("show", "Mostrar"),
        ("hidden", "Ocultar"),
    ]

    WIDTH_CHOICES = [
        ("fluid", "Ancho Fluido"),
        ("boxed", "Boxed"),
    ]

    POSITION_CHOICES = [
        ("fixed", "Fijo"),
        ("scrollable", "Desplazable"),
    ]

    TOPBAR_CHOICES = [
        ("light", "Claro"),
        ("dark", "Oscuro"),
    ]

    SIDEBAR_SIZE_CHOICES = [
        ("lg", "Grande"),
        ("md", "Mediano"),
        ("sm", "Pequeño"),
        ("sm-hover", "Pequeño (Hover)"),
    ]

    LAYOUT_STYLE_CHOICES = [
        ("default", "Por Defecto"),
        ("detached", "Separado"),
    ]

    SIDEBAR_COLOR_CHOICES = [
        ("dark", "Oscuro"),
        ("light", "Claro"),
        ("gradient", "Gradiente"),
    ]

    SIDEBAR_IMAGE_CHOICES = [
        ("none", "Sin imagen"),
        ("img-1", "Imagen 1"),
        ("img-2", "Imagen 2"),
        ("img-3", "Imagen 3"),
        ("img-4", "Imagen 4"),
    ]

    PRELOADER_CHOICES = [
        ("disable", "Desactivado"),
        ("enable", "Activado"),
    ]

    # 🧩 Preferencias visuales
    data_layout = models.CharField(max_length=50, choices=LAYOUT_CHOICES, default="vertical", blank=True, null=True)
    data_bs_theme = models.CharField(max_length=50, choices=THEME_CHOICES, default="light", blank=True, null=True)
    data_sidebar_visibility = models.CharField(max_length=50, choices=SIDEBAR_VISIBILITY_CHOICES, default="show", blank=True, null=True)
    data_layout_width = models.CharField(max_length=50, choices=WIDTH_CHOICES, default="fluid", blank=True, null=True)
    data_layout_position = models.CharField(max_length=50, choices=POSITION_CHOICES, default="fixed", blank=True, null=True)
    data_topbar = models.CharField(max_length=50, choices=TOPBAR_CHOICES, default="light", blank=True, null=True)
    data_sidebar_size = models.CharField(max_length=50, choices=SIDEBAR_SIZE_CHOICES, default="lg", blank=True, null=True)
    data_layout_style = models.CharField(max_length=50, choices=LAYOUT_STYLE_CHOICES, default="default", blank=True, null=True)
    data_sidebar = models.CharField(max_length=50, choices=SIDEBAR_COLOR_CHOICES, default="dark", blank=True, null=True)
    data_sidebar_image = models.CharField(max_length=50, choices=SIDEBAR_IMAGE_CHOICES, default="none", blank=True, null=True)
    data_preloader = models.CharField(max_length=50, choices=PRELOADER_CHOICES, default="disable", blank=True, null=True)

    # 📧 Configuración de correo electrónico
    email_enabled = models.BooleanField(default=False)
    email_protocol = models.CharField(
        max_length=10,
        choices=[("IMAP", "IMAP"), ("POP3", "POP3")],
        default="IMAP",
        blank=True,
        null=True
    )
    email_host = models.CharField(max_length=255, blank=True, null=True)
    email_port = models.IntegerField(blank=True, null=True)
    email_encryption = models.CharField(
        max_length=10,
        choices=[("NONE", "Ninguno"), ("SSL", "SSL"), ("TLS", "TLS")],
        default="SSL",
        blank=True,
        null=True
    )
    email_username = models.CharField(max_length=255, blank=True, null=True)
    email_password = models.CharField(max_length=255, blank=True, null=True)

    smtp_host = models.CharField(max_length=255, blank=True, null=True)
    smtp_port = models.IntegerField(blank=True, null=True)
    smtp_encryption = models.CharField(
        max_length=10,
        choices=[("NONE", "Ninguno"), ("SSL", "SSL"), ("STARTTLS", "STARTTLS")],
        default="STARTTLS",
        blank=True,
        null=True
    )
    smtp_username = models.CharField(max_length=255, blank=True, null=True)
    smtp_password = models.CharField(max_length=255, blank=True, null=True)

    # 🔔 Preferencias de notificación
    send_headers = models.BooleanField(default=False)
    send_documents = models.BooleanField(default=False)

    fecha_sistema = models.DateField(null=True, blank=True)

    def __str__(self):
        return f"Preferences for {self.user.username}"


class ThemePreferences(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    empresa = models.ForeignKey(Empresa, on_delete=models.CASCADE)

    # 🧩 Preferencias visuales
    data_layout = models.CharField(max_length=50, choices=UserPreferences.LAYOUT_CHOICES, default="vertical", blank=True, null=True)
    data_bs_theme = models.CharField(max_length=50, choices=UserPreferences.THEME_CHOICES, default="light", blank=True, null=True)
    data_sidebar_visibility = models.CharField(max_length=50, choices=UserPreferences.SIDEBAR_VISIBILITY_CHOICES, default="show", blank=True, null=True)
    data_layout_width = models.CharField(max_length=50, choices=UserPreferences.WIDTH_CHOICES, default="fluid", blank=True, null=True)
    data_layout_position = models.CharField(max_length=50, choices=UserPreferences.POSITION_CHOICES, default="fixed", blank=True, null=True)
    data_topbar = models.CharField(max_length=50, choices=UserPreferences.TOPBAR_CHOICES, default="light", blank=True, null=True)
    data_sidebar_size = models.CharField(max_length=50, choices=UserPreferences.SIDEBAR_SIZE_CHOICES, default="lg", blank=True, null=True)
    data_layout_style = models.CharField(max_length=50, choices=UserPreferences.LAYOUT_STYLE_CHOICES, default="default", blank=True, null=True)
    data_sidebar = models.CharField(max_length=50, choices=UserPreferences.SIDEBAR_COLOR_CHOICES, default="dark", blank=True, null=True)
    data_sidebar_image = models.CharField(max_length=50, choices=UserPreferences.SIDEBAR_IMAGE_CHOICES, default="none", blank=True, null=True)
    data_preloader = models.CharField(max_length=50, choices=UserPreferences.PRELOADER_CHOICES, default="disable", blank=True, null=True)

    class Meta:
        unique_together = ("user", "empresa")

    def __str__(self):
        return f"ThemePreferences for {self.user.username} @ {self.empresa.codigo}"


class SettingsMySQLConnection(models.Model):
    """Conexiones MySQL por empresa.

    Almacenamos por ahora las credenciales en BD (ver notas de seguridad).
    """
    TIPOS_CHOICES = [
        ("ventas", "ventas"),
        ("gestion", "gestion"),
        ("remuneraciones", "remuneraciones"),
    ]

    empresa = models.ForeignKey('access_control.Empresa', on_delete=models.CASCADE)
    nombre_logico = models.CharField(max_length=100)
    engine = models.CharField(max_length=100, default="django.db.backends.mysql")
    host = models.CharField(max_length=255)
    port = models.PositiveIntegerField(default=3306)
    user = models.CharField(max_length=150)
    password = models.CharField(max_length=255)
    db_name = models.CharField(max_length=255)
    charset = models.CharField(max_length=50, blank=True, null=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("empresa", "nombre_logico")
        ordering = ["empresa_id", "nombre_logico"]

    def __str__(self):
        return f"{self.empresa.codigo}::{self.nombre_logico} -> {self.db_name} ({self.host})"
