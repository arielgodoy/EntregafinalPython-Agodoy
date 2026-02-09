from acounts.models import CompanyConfig, SystemConfig


def _get_active_system_config():
    return SystemConfig.objects.filter(is_active=True).select_related(
        'security_email_account',
        'notifications_email_account',
        'alerts_email_account'
    ).first()


def get_effective_company_config(empresa):
    """
    Retorna un dict con configuración efectiva de empresa usando fallback a SystemConfig.
    """
    system_config = _get_active_system_config()

    company_config = CompanyConfig.objects.filter(empresa=empresa).select_related(
        'security_email_account',
        'notifications_email_account',
        'alerts_email_account'
    ).first()

    def pick(company_value, system_value):
        if company_value is None:
            return system_value
        if isinstance(company_value, str) and company_value.strip() == "":
            return system_value
        return company_value

    return {
        'company_config': company_config,
        'system_config': system_config,
        'public_base_url': pick(
            getattr(company_config, 'public_base_url', None),
            getattr(system_config, 'public_base_url', None)
        ),
        'from_email': pick(
            getattr(company_config, 'from_email', None),
            getattr(system_config, 'default_from_email', None)
        ),
        'from_name': pick(
            getattr(company_config, 'from_name', None),
            getattr(system_config, 'default_from_name', None)
        ),
        'security_email_account': pick(
            getattr(company_config, 'security_email_account', None),
            getattr(system_config, 'security_email_account', None)
        ),
        'notifications_email_account': pick(
            getattr(company_config, 'notifications_email_account', None),
            getattr(system_config, 'notifications_email_account', None)
        ),
        'alerts_email_account': pick(
            getattr(company_config, 'alerts_email_account', None),
            getattr(system_config, 'alerts_email_account', None)
        ),
        'activation_ttl_hours': pick(
            getattr(company_config, 'activation_ttl_hours', None),
            getattr(system_config, 'activation_ttl_hours', None)
        ),
        'reset_ttl_minutes': pick(
            getattr(company_config, 'reset_ttl_minutes', None),
            getattr(system_config, 'reset_ttl_minutes', None)
        ),
        'max_failed_logins': pick(
            getattr(company_config, 'max_failed_logins', None),
            getattr(system_config, 'max_failed_logins', None)
        ),
        'lock_minutes': pick(
            getattr(company_config, 'lock_minutes', None),
            getattr(system_config, 'lock_minutes', None)
        ),
    }
