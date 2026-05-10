"""Gửi email mời project (SMTP tùy chọn)."""

from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage

from .config import get_settings

_log = logging.getLogger(__name__)


def project_invite_accept_url(token: str) -> str:
    base = get_settings().public_web_url.rstrip("/")
    return f"{base}/invite/{token.strip()}"


def send_project_invite_email(
    *,
    to_email: str,
    inviter_display_name: str,
    project_name: str,
    accept_url: str,
) -> None:
    s = get_settings()
    subject = f"Bạn được mời tham gia dự án «{project_name}»"
    body = (
        f"Xin chào,\n\n"
        f"{inviter_display_name} đã mời bạn tham gia dự án «{project_name}» trên Agile Studio.\n\n"
        f"Chấp nhận lời mời (đăng nhập hoặc đăng ký bằng cùng email):\n{accept_url}\n\n"
        f"— Agile Studio\n"
    )
    if not (s.smtp_host or "").strip():
        _log.info(
            "Invite email (SMTP disabled): to=%s subject=%s url=%s — set AGILE_SMTP_HOST to send real mail",
            to_email,
            subject,
            accept_url,
        )
        return

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = s.mail_from
    msg["To"] = to_email
    msg.set_content(body)

    try:
        with smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=30) as smtp:
            if s.smtp_use_tls:
                smtp.starttls()
            if (s.smtp_user or "").strip():
                smtp.login(s.smtp_user, s.smtp_password)
            smtp.send_message(msg)
        _log.info("Invite email sent to %s", to_email)
    except Exception:
        _log.exception("Failed to send invite email to %s", to_email)
        raise
