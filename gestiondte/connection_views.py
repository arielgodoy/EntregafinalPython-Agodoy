from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core import signing
from django.db import transaction
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.decorators import method_decorator
from django.views import View
from typing import cast

from access_control.decorators import verificar_permiso
from access_control.models import Empresa, Permiso, Vista
from access_control.views import VerificarPermisoMixin

from .forms import GestionDTEConnectionRoleForm
from .models import GestionDTEConnectionRole
from .services.base_dte_schema import (
    BaseDTESchemaInstallError,
    install_base_dte_schema,
    preview_base_dte_schema,
)
from .services.connection_roles import (
    GestionDTEConnectionError,
    get_gestiondte_connection,
    get_gestiondte_connection_status,
    get_gestiondte_mysql_connection,
)
from settings.models import SettingsMySQLConnection

_BASE_DTE_SCHEMA_PREVIEW_SALT = 'gestiondte.base-dte-schema-preview'
_BASE_DTE_SCHEMA_PREVIEW_MAX_AGE = 600


class GestionDTEConnectionRoleView(VerificarPermisoMixin, LoginRequiredMixin, View):
    template_name = 'gestiondte/connection_roles.html'
    vista_nombre = 'Gestion DTE - Conexiones SQL'
    permiso_requerido = 'ingresar'
    verificar_vicmeas_en_dispatch = False

    def _role_instances(self):
        existing = {
            item.role: item
            for item in GestionDTEConnectionRole.objects.select_related(
                'mysql_connection', 'mysql_connection__empresa'
            )
        }
        return [
            (role, label, existing.get(role))
            for role, label in GestionDTEConnectionRole.ROLE_CHOICES
        ]

    def _active_empresa(self):
        empresa_id = self.request.session.get('empresa_id')
        return Empresa.objects.filter(pk=empresa_id).first() if empresa_id else None

    def _context(self, forms):
        status = get_gestiondte_connection_status()
        vista = Vista.objects.filter(nombre=self.vista_nombre).first()
        empresa_id = self.request.session.get('empresa_id') if hasattr(self, 'request') else None
        roles = cast(list[dict[str, object]], status['roles'])
        base_dte_status = next(
            (item for item in roles if item['role'] == 'serverbasedte'),
            None,
        )
        base_dte_database_name = None
        if (
            base_dte_status
            and base_dte_status['status'] == 'configured'
            and base_dte_status['source_type'] == 'MYSQL_CONFIG'
        ):
            metadata = base_dte_status.get('metadata')
            if isinstance(metadata, dict):
                configured_database = metadata.get('database_name')
                if isinstance(configured_database, str):
                    base_dte_database_name = configured_database
        can_install_base_dte = bool(
            vista
            and empresa_id
            and Permiso.objects.filter(
                usuario=self.request.user,
                empresa_id=empresa_id,
                vista=vista,
                supervisor=True,
            ).exists()
            and base_dte_database_name
        )
        return {
            'role_forms': forms,
            'connection_status': status,
            'can_install_base_dte': can_install_base_dte,
            'base_dte_database_name': base_dte_database_name,
            'vista_nombre': self.vista_nombre,
        }

    @method_decorator(verificar_permiso(vista_nombre, 'ingresar'))
    def get(self, request):
        forms = []
        for role, label, instance in self._role_instances():
            form = GestionDTEConnectionRoleForm(
                prefix=f'role-{role}',
                instance=instance or GestionDTEConnectionRole(role=role),
                role=role,
                empresa=self._active_empresa(),
            )
            forms.append({'role': role, 'label': label, 'form': form})
        return render(request, self.template_name, self._context(forms))

    @method_decorator(verificar_permiso(vista_nombre, 'modificar'))
    def post(self, request):
        forms = []
        for role, label, instance in self._role_instances():
            form = GestionDTEConnectionRoleForm(
                request.POST,
                prefix=f'role-{role}',
                instance=instance or GestionDTEConnectionRole(role=role),
                role=role,
                empresa=self._active_empresa(),
            )
            forms.append({'role': role, 'label': label, 'form': form})

        if not all(item['form'].is_valid() for item in forms):
            return render(request, self.template_name, self._context(forms), status=400)

        with transaction.atomic():
            for item in forms:
                item['form'].save()
        messages.success(request, 'La configuración de conexiones SQL fue guardada.')
        return redirect(reverse('gestion_dte:connection_roles'))


@method_decorator(
    verificar_permiso('Gestion DTE - Conexiones SQL', 'supervisor'),
    name='dispatch',
)
class BaseDTESchemaInstallView(LoginRequiredMixin, View):
    def _render_connection_roles(
        self,
        request,
        schema_preview=None,
        schema_preview_token=None,
    ):
        page = GestionDTEConnectionRoleView()
        page.request = request
        empresa = page._active_empresa()
        forms = []
        for role, label, instance in page._role_instances():
            form = GestionDTEConnectionRoleForm(
                prefix=f'role-{role}',
                instance=instance or GestionDTEConnectionRole(role=role),
                role=role,
                empresa=empresa,
            )
            forms.append({'role': role, 'label': label, 'form': form})
        context = page._context(forms)
        context['schema_preview'] = schema_preview
        context['schema_preview_token'] = schema_preview_token
        return render(request, page.template_name, context)

    def _resolve_serverbasedte(
        self,
        empresa=None,
    ) -> tuple[dict[str, object] | None, SettingsMySQLConnection | None, str | None]:
        source = (
            get_gestiondte_connection('serverbasedte', empresa=empresa)
            if empresa is not None
            else get_gestiondte_connection('serverbasedte')
        )
        if source['type'] != 'MYSQL_CONFIG':
            return None, None, None
        connection_config = (
            get_gestiondte_mysql_connection('serverbasedte', empresa=empresa)
            if empresa is not None
            else get_gestiondte_mysql_connection('serverbasedte')
        )
        if not isinstance(connection_config, SettingsMySQLConnection):
            raise BaseDTESchemaInstallError(
                'La configuración Base DTE no es válida.'
            )
        database_name = source.get('database_name')
        if (
            not isinstance(database_name, str)
            or not GestionDTEConnectionRole.DATABASE_NAME_PATTERN.fullmatch(database_name)
        ):
            raise BaseDTESchemaInstallError(
                'La base de datos del rol Base DTE no está configurada o no es válida.'
            )
        if source.get('connection_id') != connection_config.pk:
            raise BaseDTESchemaInstallError(
                'La conexión Base DTE cambió durante la operación; vuelva a intentarlo.'
            )
        return source, connection_config, database_name

    def post(self, request):
        try:
            action = request.POST.get('schema_action')
            empresa = Empresa.objects.filter(
                pk=request.session.get('empresa_id')
            ).first()
            source, connection_config, database_name = self._resolve_serverbasedte(empresa)
            if source is None:
                messages.info(
                    request,
                    'Base DTE utiliza una base administrada por Django; no requiere creación manual de estructura.',
                )
                return redirect('gestion_dte:connection_roles')
            if connection_config is None or database_name is None:
                raise BaseDTESchemaInstallError(
                    'La configuración Base DTE no está completa.'
                )
            if action == 'preview':
                schema_preview = preview_base_dte_schema(
                    connection_config,
                    database_name,
                )
                token = None
                if schema_preview['missing'] and not schema_preview['conflicts']:
                    token = signing.dumps(
                        {
                            'connection_id': connection_config.pk,
                            'connection_updated_at': connection_config.updated_at.isoformat(),
                            'database_name': database_name,
                            'fingerprint': schema_preview['fingerprint'],
                        },
                        salt=_BASE_DTE_SCHEMA_PREVIEW_SALT,
                        compress=True,
                    )
                return self._render_connection_roles(
                    request,
                    schema_preview=schema_preview,
                    schema_preview_token=token,
                )

            if action != 'confirm':
                raise BaseDTESchemaInstallError(
                    'La operación requiere una vista previa y confirmación explícitas.'
                )
            try:
                preview_data = signing.loads(
                    request.POST.get('schema_preview_token', ''),
                    salt=_BASE_DTE_SCHEMA_PREVIEW_SALT,
                    max_age=_BASE_DTE_SCHEMA_PREVIEW_MAX_AGE,
                )
            except signing.BadSignature as exc:
                raise BaseDTESchemaInstallError(
                    'La vista previa expiró o no es válida; vuelva a inspeccionar la estructura.'
                ) from exc
            if not isinstance(preview_data, dict):
                raise BaseDTESchemaInstallError(
                    'La vista previa no es válida; vuelva a inspeccionar la estructura.'
                )
            fingerprint = preview_data.get('fingerprint')
            if not isinstance(fingerprint, str) or not fingerprint:
                raise BaseDTESchemaInstallError(
                    'La vista previa no es válida; vuelva a inspeccionar la estructura.'
                )
            if (
                preview_data.get('connection_id') != connection_config.pk
                or preview_data.get('connection_updated_at')
                != connection_config.updated_at.isoformat()
                or preview_data.get('database_name') != database_name
            ):
                raise BaseDTESchemaInstallError(
                    'El destino cambió desde la vista previa; vuelva a inspeccionar la estructura.'
                )
            result = install_base_dte_schema(
                connection_config,
                database_name=database_name,
                expected_fingerprint=fingerprint,
            )
            if result['error_type']:
                messages.error(
                    request,
                    'Creación parcial: '
                    f"tabla={result['error_table']}; "
                    f"error={result['error_type']}; "
                    f"creadas={', '.join(result['created']) or 'ninguna'}; "
                    f"pendientes={', '.join(result['pending']) or 'ninguna'}; "
                    f"conflictos={', '.join(item['name'] for item in result['conflicts']) or 'ninguno'}. "
                    'Las operaciones DDL anteriores no se revierten automáticamente.',
                )
            elif result['conflicts']:
                messages.error(
                    request,
                    'La estructura detectó conflictos y no se creó ninguna tabla.',
                )
            elif result['created']:
                messages.success(
                    request,
                    'Estructura Base DTE creada: '
                    + ', '.join(result['created']),
                )
            else:
                messages.success(
                    request,
                    'La estructura Base DTE ya existe y es compatible; no se realizaron cambios.',
                )
        except BaseDTESchemaInstallError as exc:
            messages.error(request, str(exc))
        except GestionDTEConnectionError:
            messages.error(
                request,
                'No se pudo resolver la conexión configurada para el rol Base DTE.',
            )
        return redirect('gestion_dte:connection_roles')