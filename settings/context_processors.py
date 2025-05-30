from .models import UserPreferences

def user_preferences_to_localstorage(request):
    if not request.user.is_authenticated:
        return {}

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
