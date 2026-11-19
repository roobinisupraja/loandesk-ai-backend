import os, smtplib, ssl
from email.message import EmailMessage

def _send(host, port, user, pw, ctx, msg):
    if port == 465:
        with smtplib.SMTP_SSL(host, port, context=ctx, timeout=20) as s:
            if user: s.login(user, pw or "")
            s.send_message(msg)
    else:
        with smtplib.SMTP(host, port, timeout=20) as s:
            if os.getenv("SMTP_STARTTLS", "true").lower() != "false":
                s.starttls(context=ctx)
            if user: s.login(user, pw or "")
            s.send_message(msg)

def send_smtp(to: str, subject: str, body: str) -> str:
    """Send a plain-text email over SMTP. Returns 'sent' or 'skipped: ...'. Raises RuntimeError with a readable reason on failure."""
    host = os.getenv("SMTP_HOST")
    if not host:
        return "skipped: SMTP not configured"
    port = int(os.getenv("SMTP_PORT", "587"))
    user, pw = os.getenv("SMTP_USER"), os.getenv("SMTP_PASSWORD")
    msg = EmailMessage()
    msg["From"] = os.getenv("SMTP_FROM") or user or "loandesk@localhost"
    msg["To"], msg["Subject"] = to, subject
    msg.set_content(body)
    try:
        _send(host, port, user, pw, ssl.create_default_context(), msg)
    except smtplib.SMTPAuthenticationError as e:
        raise RuntimeError("SMTP login rejected. For Gmail use an App Password, not your normal password.") from e
    except smtplib.SMTPRecipientsRefused as e:
        raise RuntimeError(f"Recipient address refused: {to}") from e
    except (TimeoutError, OSError) as e:
        raise RuntimeError(f"Could not connect to {host}:{port} ({e})") from e
    return "sent"
