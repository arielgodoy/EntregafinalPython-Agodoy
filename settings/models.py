from django.db import models
from django.contrib.auth.models import User

class UserPreferences(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)

    # 🖥️ Preferencias de tema/layout (valores por defecto del sistema)
    
    # Opciones de configuración posibles según layout.js
    LAYOUT_CHOICES = [
        ("vertical", "Vertical"),
        ("horizontal", "Horizontal"),
        ("twocolumn", "Two Column"),
        ("semibox", "Semi Boxed"),
    ]

    THEME_CHOICES = [
        ("light", "Light"),
        ("dark", "Dark"),
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

    data_layout = models.CharField(max_length=50, blank=True, null=True, default="vertical")
    data_bs_theme = models.CharField(max_length=50, blank=True, null=True, default="light")
    data_sidebar_visibility = models.CharField(max_length=50, blank=True, null=True, default="show")
    data_layout_width = models.CharField(max_length=50, blank=True, null=True, default="fluid")
    data_layout_position = models.CharField(max_length=50, blank=True, null=True, default="fixed")
    data_topbar = models.CharField(max_length=50, blank=True, null=True, default="light")
    data_sidebar_size = models.CharField(max_length=50, blank=True, null=True, default="lg")
    data_layout_style = models.CharField(max_length=50, blank=True, null=True, default="default")
    data_sidebar = models.CharField(max_length=50, blank=True, null=True, default="dark")
    data_sidebar_image = models.CharField(max_length=50, blank=True, null=True, default="none")
    data_preloader = models.CharField(max_length=50, blank=True, null=True, default="disable")

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

    # Preferencias de notificación
    send_headers = models.BooleanField(default=False)
    send_documents = models.BooleanField(default=False)

    def __str__(self):
        return f"Preferences for {self.user.username}"
