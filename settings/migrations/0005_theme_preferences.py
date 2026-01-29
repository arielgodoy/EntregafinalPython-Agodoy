from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("access_control", "0001_initial"),
        ("settings", "0004_alter_userpreferences_data_bs_theme_and_more"),
    ]

    operations = [
        migrations.CreateModel(
            name="ThemePreferences",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("data_layout", models.CharField(blank=True, choices=[("vertical", "Vertical"), ("horizontal", "Horizontal"), ("twocolumn", "Two Column"), ("semibox", "Semi Boxed")], default="vertical", max_length=50, null=True)),
                ("data_bs_theme", models.CharField(blank=True, choices=[("light", "Claro"), ("dark", "Oscuro")], default="light", max_length=50, null=True)),
                ("data_sidebar_visibility", models.CharField(blank=True, choices=[("show", "Mostrar"), ("hidden", "Ocultar")], default="show", max_length=50, null=True)),
                ("data_layout_width", models.CharField(blank=True, choices=[("fluid", "Ancho Fluido"), ("boxed", "Boxed")], default="fluid", max_length=50, null=True)),
                ("data_layout_position", models.CharField(blank=True, choices=[("fixed", "Fijo"), ("scrollable", "Desplazable")], default="fixed", max_length=50, null=True)),
                ("data_topbar", models.CharField(blank=True, choices=[("light", "Claro"), ("dark", "Oscuro")], default="light", max_length=50, null=True)),
                ("data_sidebar_size", models.CharField(blank=True, choices=[("lg", "Grande"), ("md", "Mediano"), ("sm", "Pequeño"), ("sm-hover", "Pequeño (Hover)")], default="lg", max_length=50, null=True)),
                ("data_layout_style", models.CharField(blank=True, choices=[("default", "Por Defecto"), ("detached", "Separado")], default="default", max_length=50, null=True)),
                ("data_sidebar", models.CharField(blank=True, choices=[("dark", "Oscuro"), ("light", "Claro"), ("gradient", "Gradiente")], default="dark", max_length=50, null=True)),
                ("data_sidebar_image", models.CharField(blank=True, choices=[("none", "Sin imagen"), ("img-1", "Imagen 1"), ("img-2", "Imagen 2"), ("img-3", "Imagen 3"), ("img-4", "Imagen 4")], default="none", max_length=50, null=True)),
                ("data_preloader", models.CharField(blank=True, choices=[("disable", "Desactivado"), ("enable", "Activado")], default="disable", max_length=50, null=True)),
                ("empresa", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to="access_control.empresa")),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to="auth.user")),
            ],
            options={
                "unique_together": {("user", "empresa")},
            },
        ),
    ]
