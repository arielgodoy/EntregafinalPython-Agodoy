from .models import UserPreferences


THEME_PREFERENCE_DEFAULTS = {
    "data-layout": "vertical",
    "data-bs-theme": "light",
    "data-sidebar-visibility": "show",
    "data-layout-width": "fluid",
    "data-layout-position": "fixed",
    "data-topbar": "light",
    "data-sidebar-size": "lg",
    "data-layout-style": "default",
    "data-sidebar": "dark",
    "data-sidebar-image": "none",
    "data-preloader": "disable",
}


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

    visual_fields = {
        "data-layout": "data_layout",
        "data-bs-theme": "data_bs_theme",
        "data-sidebar-visibility": "data_sidebar_visibility",
        "data-layout-width": "data_layout_width",
        "data-layout-position": "data_layout_position",
        "data-topbar": "data_topbar",
        "data-sidebar-size": "data_sidebar_size",
        "data-layout-style": "data_layout_style",
        "data-sidebar": "data_sidebar",
        "data-sidebar-image": "data_sidebar_image",
        "data-preloader": "data_preloader",
    }
    values = UserPreferences.objects.filter(user=request.user).values(
        *visual_fields.values()
    ).first() or {}

    return {
        "theme_preferences": {
            key: values.get(field) or THEME_PREFERENCE_DEFAULTS[key]
            for key, field in visual_fields.items()
        }
    }
