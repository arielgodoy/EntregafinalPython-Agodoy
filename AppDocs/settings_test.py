from .settings import *  # noqa

import os
import sys
import types
from django.db import models as django_models


os.environ.setdefault('RUNNING_TESTS', '1')

# Compatibility shim: ensure TextChoices exists in django.db.models for older Django
try:
    import enum as _enum
    if not hasattr(django_models, 'TextChoices'):
        class TextChoicesMeta(_enum.EnumMeta):
            def __new__(mcls, name, bases, namespace, **kwargs):
                enum_cls = super().__new__(mcls, name, bases, namespace)
                try:
                    choices = tuple((member.value, getattr(member, 'label', member.name.title())) for member in enum_cls)
                except Exception:
                    choices = tuple()
                setattr(enum_cls, 'choices', choices)
                return enum_cls

        class TextChoices(str, _enum.Enum, metaclass=TextChoicesMeta):
            def __new__(cls, value, label=None):
                obj = str.__new__(cls, value)
                obj._value_ = value
                obj.label = label or value
                return obj

        django_models.TextChoices = TextChoices
except Exception:
    pass

# Compatibility shim: JSONField for older Django versions
try:
    if not hasattr(django_models, 'JSONField'):
        class JSONField(django_models.TextField):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)

        django_models.JSONField = JSONField
except Exception:
    pass


def _ensure_ckeditor_stub():
    if 'ckeditor' in sys.modules:
        return
    ckeditor_module = types.ModuleType('ckeditor')
    fields_module = types.ModuleType('ckeditor.fields')

    class RichTextField(django_models.TextField):
        pass

    fields_module.RichTextField = RichTextField
    ckeditor_module.fields = fields_module

    sys.modules['ckeditor'] = ckeditor_module
    sys.modules['ckeditor.fields'] = fields_module


try:
    import ckeditor  # noqa: F401
except ImportError:
    _ensure_ckeditor_stub()
    INSTALLED_APPS = [app for app in INSTALLED_APPS if app != 'ckeditor']


try:
    import crispy_forms  # noqa: F401
except ImportError:
    INSTALLED_APPS = [app for app in INSTALLED_APPS if app != 'crispy_forms']

try:
    import crispy_bootstrap5  # noqa: F401
except ImportError:
    INSTALLED_APPS = [app for app in INSTALLED_APPS if app != 'crispy_bootstrap5']


try:
    import rest_framework  # noqa: F401
except ImportError:
    INSTALLED_APPS = [app for app in INSTALLED_APPS if app != 'rest_framework']

    rest_framework_module = types.ModuleType('rest_framework')
    routers_module = types.ModuleType('rest_framework.routers')
    viewsets_module = types.ModuleType('rest_framework.viewsets')
    response_module = types.ModuleType('rest_framework.response')
    filters_module = types.ModuleType('rest_framework.filters')
    permissions_module = types.ModuleType('rest_framework.permissions')
    serializers_module = types.ModuleType('rest_framework.serializers')
    decorators_module = types.ModuleType('rest_framework.decorators')
    status_module = types.ModuleType('rest_framework.status')

    class DefaultRouter:
        def __init__(self):
            self.registry = []

        def register(self, *args, **kwargs):
            self.registry.append((args, kwargs))

        @property
        def urls(self):
            return []

    class ViewSet:
        pass

    class ReadOnlyModelViewSet:
        pass

    class ModelViewSet(ReadOnlyModelViewSet):
        pass

    class Response:  # minimal stub
        def __init__(self, data=None, status=None, *args, **kwargs):
            self.data = data
            self.status = status

    class SearchFilter:
        pass

    class OrderingFilter:
        pass

    class IsAuthenticated:
        pass

    class Serializer:
        pass

    class Field:
        def __init__(self, *args, **kwargs):
            pass

    class CharField(Field):
        pass

    class SerializerMethodField(Field):
        pass

    class ModelSerializer(Serializer):
        pass

    def action(*args, **kwargs):
        def decorator(func):
            return func
        return decorator

    routers_module.DefaultRouter = DefaultRouter
    viewsets_module.ViewSet = ViewSet
    viewsets_module.ReadOnlyModelViewSet = ReadOnlyModelViewSet
    viewsets_module.ModelViewSet = ModelViewSet
    response_module.Response = Response
    filters_module.SearchFilter = SearchFilter
    filters_module.OrderingFilter = OrderingFilter
    permissions_module.IsAuthenticated = IsAuthenticated
    serializers_module.Serializer = Serializer
    serializers_module.ModelSerializer = ModelSerializer
    serializers_module.Field = Field
    serializers_module.CharField = CharField
    serializers_module.SerializerMethodField = SerializerMethodField
    decorators_module.action = action
    status_module.HTTP_400_BAD_REQUEST = 400
    status_module.HTTP_403_FORBIDDEN = 403
    status_module.HTTP_204_NO_CONTENT = 204

    rest_framework_module.routers = routers_module
    rest_framework_module.viewsets = viewsets_module
    rest_framework_module.response = response_module
    rest_framework_module.filters = filters_module
    rest_framework_module.permissions = permissions_module
    rest_framework_module.serializers = serializers_module
    rest_framework_module.decorators = decorators_module
    rest_framework_module.status = status_module

    sys.modules['rest_framework'] = rest_framework_module
    sys.modules['rest_framework.routers'] = routers_module
    sys.modules['rest_framework.viewsets'] = viewsets_module
    sys.modules['rest_framework.response'] = response_module
    sys.modules['rest_framework.filters'] = filters_module
    sys.modules['rest_framework.permissions'] = permissions_module
    sys.modules['rest_framework.serializers'] = serializers_module
    sys.modules['rest_framework.decorators'] = decorators_module
    sys.modules['rest_framework.status'] = status_module


DATABASES['default'] = {
    'ENGINE': 'django.db.backends.sqlite3',
    'NAME': ':memory:',
}

try:
    import PIL  # noqa: F401
except ImportError:
    SILENCED_SYSTEM_CHECKS = ['fields.E210']

try:
    import channels  # noqa: F401
except ImportError:
    INSTALLED_APPS = [app for app in INSTALLED_APPS if app != 'channels']

MIGRATION_MODULES = {
    'access_control': None,
    'acounts': None,
    'api': None,
    'biblioteca': None,
    'chat': None,
    'control_operacional': None,
    'control_de_proyectos': None,
    'evaluaciones': None,
    'settings': None,
    'notificaciones': None,
}
