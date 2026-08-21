from django.contrib.auth.decorators import login_required
from django.shortcuts import render


@login_required
def dashboard_general(request):
    """Landing común para usuarios autenticados."""
    return render(request, 'dashboard/dashboard_general.html')
