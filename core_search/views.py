from django.contrib.auth.decorators import login_required
from django.http import JsonResponse

from .services import search_pages_for_user


@login_required
def menu_search(request):
    empresa_id = request.session.get("empresa_id")
    query = (request.GET.get("q") or "").strip()
    pages = search_pages_for_user(request.user, empresa_id, query)
    return JsonResponse({"q": query, "pages": pages})
