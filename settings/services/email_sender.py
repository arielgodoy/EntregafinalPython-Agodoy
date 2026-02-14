import smtplib
from email.message import EmailMessage
from email.utils import formatdate, make_msgid


def _build_smtp_server(prefs, timeout=10):
    if prefs.smtp_encryption == "SSL":
        server = smtplib.SMTP_SSL(prefs.smtp_host, prefs.smtp_port, timeout=timeout)
    else:
        server = smtplib.SMTP(prefs.smtp_host, prefs.smtp_port, timeout=timeout)
        if prefs.smtp_encryption == "STARTTLS":
            server.starttls()
    return server


def send_email_message(prefs, message):
    server = _build_smtp_server(prefs)
    try:
        server.login(prefs.smtp_username, prefs.smtp_password)
        server.send_message(message)
    finally:
        server.quit()


def build_plain_email(subject, body, from_email, to_emails, reply_to=None):
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = from_email
    msg["To"] = ", ".join(to_emails)
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid()
    if reply_to:
        msg["Reply-To"] = reply_to
    msg.set_content(body)
    return msg
