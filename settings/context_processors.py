from .models import UserPreferences, ThemePreferences


def system_date_context(request):
    if not request.user.is_authenticated:
        return {}

    fecha = request.session.get("fecha_sistema")
    if not fecha:
        prefs = UserPreferences.objects.filter(user=request.user).first()
        if prefs and prefs.fecha_sistema:
            fecha = prefs.fecha_sistema.isoformat()
            request.session["fecha_sistema"] = fecha

    return {"fecha_sistema": fecha}

def user_preferences_to_localstorage(request):
    if not request.user.is_authenticated:
        return {}

    empresa_id = request.session.get("empresa_id")
    if not empresa_id:
        return {}

    try:
        prefs = ThemePreferences.objects.get(user=request.user, empresa_id=empresa_id)

        return {
            "theme_preferences": {
                "data-layout": prefs.data_layout,
                "data-bs-theme": prefs.data_bs_theme,
                "data-sidebar-visibility": prefs.data_sidebar_visibility,
                "data-layout-width": prefs.data_layout_width,
                "data-layout-position": prefs.data_layout_position,
                "data-topbar": prefs.data_topbar,
                "data-sidebar-size": prefs.data_sidebar_size,
                "data-layout-style": prefs.data_layout_style,
                "data-sidebar": prefs.data_sidebar,
                "data-sidebar-image": prefs.data_sidebar_image,
                "data-preloader": prefs.data_preloader,
            }
        }

    except ThemePreferences.DoesNotExist:
        try:
            prefs = UserPreferences.objects.get(user=request.user)
            return {
                "theme_preferences": {
                    "data-layout": prefs.data_layout,
                    "data-bs-theme": prefs.data_bs_theme,
                    "data-sidebar-visibility": prefs.data_sidebar_visibility,
                    "data-layout-width": prefs.data_layout_width,
                    "data-layout-position": prefs.data_layout_position,
                    "data-topbar": prefs.data_topbar,
                    "data-sidebar-size": prefs.data_sidebar_size,
                    "data-layout-style": prefs.data_layout_style,
                    "data-sidebar": prefs.data_sidebar,
                    "data-sidebar-image": prefs.data_sidebar_image,
                    "data-preloader": prefs.data_preloader,
                }
            }
        except UserPreferences.DoesNotExist:
            return {}
