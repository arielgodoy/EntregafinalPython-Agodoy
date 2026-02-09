import smtplib
from email.message import EmailMessage
from email.utils import formatdate, make_msgid

from django.core.mail import EmailMultiAlternatives, get_connection

from acounts.services.config import get_effective_company_config


PURPOSE_ACCOUNT_MAP = {
    'security': 'security_email_account',
    'notifications': 'notifications_email_account',
    'alerts': 'alerts_email_account',
}


def _normalize_recipients(to_emails):
    if isinstance(to_emails, (list, tuple, set)):
        return list(to_emails)
    return [to_emails]


def send_email_for_purpose(
    empresa,
    purpose,
    subject,
    body_text,
    to_emails,
    body_html=None,
    reply_to=None
):
    config = get_effective_company_config(empresa)
    if not config:
        raise ValueError('Configuración no encontrada para la empresa.')

    account_key = PURPOSE_ACCOUNT_MAP.get(purpose)
    if not account_key:
        raise ValueError('Purpose inválido. Use: security, notifications o alerts.')

    email_account = config.get(account_key)
    if not email_account or not email_account.is_active:
        raise ValueError('EmailAccount no disponible para el purpose indicado.')

    recipients = _normalize_recipients(to_emails)

    msg = EmailMessage()
    msg['Subject'] = subject
    msg['From'] = f"{email_account.from_name} <{email_account.from_email}>"
    msg['To'] = ', '.join(recipients)
    msg['Date'] = formatdate(localtime=True)
    msg['Message-ID'] = make_msgid()

    final_reply_to = reply_to or email_account.reply_to
    if final_reply_to:
        msg['Reply-To'] = final_reply_to

    msg.set_content(body_text)
    if body_html:
        msg.add_alternative(body_html, subtype='html')

    if email_account.use_ssl:
        server = smtplib.SMTP_SSL(email_account.smtp_host, email_account.smtp_port)
    else:
        server = smtplib.SMTP(email_account.smtp_host, email_account.smtp_port)
        if email_account.use_tls:
            server.starttls()

    try:
        server.login(email_account.smtp_user, email_account.smtp_password)
        server.send_message(msg)
    finally:
        server.quit()

    return {'success': True, 'recipients': recipients}


def send_security_email(
    empresa,
    subject,
    body_text,
    to_emails,
    body_html=None,
    reply_to=None,
):
    return send_email_for_purpose(
        empresa=empresa,
        purpose='security',
        subject=subject,
        body_text=body_text,
        to_emails=to_emails,
        body_html=body_html,
        reply_to=reply_to,
    )


def send_email_via_account(
    email_account,
    subject,
    body_text,
    to_emails,
    body_html=None,
    reply_to=None,
):
    if not email_account:
        raise ValueError('EmailAccount requerido para enviar correo.')

    recipients = _normalize_recipients(to_emails)

    from_display = f"{email_account.from_name} <{email_account.from_email}>"
    connection = get_connection(
        host=email_account.smtp_host,
        port=email_account.smtp_port,
        username=email_account.smtp_user,
        password=email_account.smtp_password,
        use_tls=email_account.use_tls,
        use_ssl=email_account.use_ssl,
    )

    final_reply_to = reply_to or email_account.reply_to
    reply_to_list = [final_reply_to] if final_reply_to else None

    msg = EmailMultiAlternatives(
        subject=subject,
        body=body_text,
        from_email=from_display,
        to=recipients,
        reply_to=reply_to_list,
        connection=connection,
    )
    if body_html:
        msg.attach_alternative(body_html, "text/html")

    msg.send()
    return {'success': True, 'recipients': recipients}
