from django.conf import settings
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import render
from django.views import View

from access_control.services.access_requests import build_access_request_context
from access_control.views import VerificarPermisoMixin
from common.database_classification import (
    DatabaseClassification,
    get_database_classification,
)

from .forms import DatabaseCompareForm
from .services.comparison import compare_databases
from .services.preflight import run_preflight


VISTA_DASHBOARD = 'Gestión de Bases - Dashboard'
VISTA_COMPARE = 'Gestión de Bases - Comparar'
VISTA_PREFLIGHT = 'Gestión de Bases - Preflight'


def _configured_system_aliases():
    aliases = []
    for alias, config in settings.DATABASES.items():
        if get_database_classification(alias) is DatabaseClassification.SYSTEM:
            aliases.append({
                'alias': alias,
                'vendor': config.get('ENGINE', '').rsplit('.', 1)[-1],
                'classification': DatabaseClassification.SYSTEM.value,
            })
    return sorted(aliases, key=lambda item: item['alias'])


def _comparison_context(result):
    if result is None:
        return None

    result['source_managed_table_count'] = max(
        len(result['managed_tables_expected']) - len(result['missing_in_source']), 0
    )
    result['target_managed_table_count'] = max(
        len(result['managed_tables_expected']) - len(result['missing_in_target']), 0
    )
    result['table_count_rows'] = sorted(
        (
            {'table': table, **counts}
            for table, counts in result['table_counts'].items()
        ),
        key=lambda item: (item['difference'] == 0, item['table']),
    )
    result['table_count_difference_count'] = sum(
        row['difference'] != 0 for row in result['table_count_rows']
    )
    result['pk_max_rows'] = [
        {'table': table, **values}
        for table, values in sorted(result['pk_max_values'].items())
    ]
    return result


class DatabaseManagerDashboardView(LoginRequiredMixin, VerificarPermisoMixin, View):
    vista_nombre = VISTA_DASHBOARD
    permiso_requerido = 'ingresar'

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return super().dispatch(request, *args, **kwargs)
        if not request.session.get('empresa_id'):
            context = build_access_request_context(
                request,
                self.vista_nombre,
                'Empresa activa requerida.',
            )
            return render(request, 'access_control/403_forbidden.html', context, status=403)
        return super().dispatch(request, *args, **kwargs)

    def get(self, request, *args, **kwargs):
        return render(
            request,
            'database_manager/dashboard.html',
            {'database_aliases': _configured_system_aliases()},
        )


class DatabaseCompareView(LoginRequiredMixin, VerificarPermisoMixin, View):
    vista_nombre = VISTA_COMPARE
    permiso_requerido = 'ingresar'

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return super().dispatch(request, *args, **kwargs)
        if not request.session.get('empresa_id'):
            context = build_access_request_context(
                request,
                self.vista_nombre,
                'Empresa activa requerida.',
            )
            return render(request, 'access_control/403_forbidden.html', context, status=403)
        return super().dispatch(request, *args, **kwargs)

    def _render_comparison(self, request, data):
        form = DatabaseCompareForm(data or None)
        result = None
        if data:
            if form.is_valid():
                result = _comparison_context(
                    compare_databases(
                        form.cleaned_data['source_alias'],
                        form.cleaned_data['target_alias'],
                    ).to_dict()
                )
        return render(request, 'database_manager/compare.html', {'form': form, 'result': result})

    def get(self, request, *args, **kwargs):
        return self._render_comparison(request, request.GET)

    def post(self, request, *args, **kwargs):
        return self._render_comparison(request, request.POST)


class DatabasePreflightView(LoginRequiredMixin, VerificarPermisoMixin, View):
    vista_nombre = VISTA_PREFLIGHT
    permiso_requerido = 'ingresar'

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return super().dispatch(request, *args, **kwargs)
        if not request.session.get('empresa_id'):
            context = build_access_request_context(
                request,
                self.vista_nombre,
                'Empresa activa requerida.',
            )
            return render(request, 'access_control/403_forbidden.html', context, status=403)
        return super().dispatch(request, *args, **kwargs)

    def _render_preflight(self, request, data):
        form = DatabaseCompareForm(data or None)
        result = None
        if data and form.is_valid():
            result = run_preflight(
                form.cleaned_data['source_alias'],
                form.cleaned_data['target_alias'],
            ).to_dict()
        return render(request, 'database_manager/preflight.html', {'form': form, 'result': result})

    def get(self, request, *args, **kwargs):
        return self._render_preflight(request, request.GET)

    def post(self, request, *args, **kwargs):
        return self._render_preflight(request, request.POST)
