"""Request context helpers for the tareas application."""


def get_active_company_id(request):
    """Return the active company selected in the session.

    Authorization remains delegated to the existing ICMEAS mixins and decorators;
    this helper only centralizes the session lookup.
    """
    return request.session.get("empresa_id")
