from django import forms
from django.conf import settings

from common.database_classification import (
    DatabaseClassification,
    get_database_classification,
)


def _system_alias_choices():
    choices = []
    for alias, config in settings.DATABASES.items():
        if get_database_classification(alias) is not DatabaseClassification.SYSTEM:
            continue
        vendor = config.get('ENGINE', '').rsplit('.', 1)[-1]
        choices.append((alias, f'{alias} ({vendor})'))
    return sorted(choices)


class DatabaseCompareForm(forms.Form):
    source_alias = forms.ChoiceField(choices=(), label='Base de origen')
    target_alias = forms.ChoiceField(choices=(), label='Base de destino')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        choices = _system_alias_choices()
        self.fields['source_alias'].choices = choices
        self.fields['target_alias'].choices = choices

    def clean(self):
        cleaned_data = super().clean()
        source_alias = cleaned_data.get('source_alias')
        target_alias = cleaned_data.get('target_alias')
        if source_alias and target_alias:
            for alias in (source_alias, target_alias):
                if get_database_classification(alias) is not DatabaseClassification.SYSTEM:
                    raise forms.ValidationError('Solo se permiten bases SYSTEM.')
        return cleaned_data
