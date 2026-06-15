import smtplib
import time
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import formataddr

from app.config import Settings


@dataclass(frozen=True)
class EmailSendResult:
    status: str
    latency_ms: int
    error_message: str | None = None


class EmailNotifier:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def send_email(
        self,
        *,
        to_email: str,
        subject: str,
        text_content: str,
        html_content: str | None = None,
    ) -> EmailSendResult:
        start = time.perf_counter()
        try:
            self._validate_settings()
            message = self._build_message(
                to_email=to_email,
                subject=subject,
                text_content=text_content,
                html_content=html_content,
            )
            self._send(message)
            return EmailSendResult(status="success", latency_ms=_elapsed_ms(start))
        except Exception as exc:  # pragma: no cover - network boundary
            return EmailSendResult(
                status="failed",
                latency_ms=_elapsed_ms(start),
                error_message=str(exc),
            )

    def _validate_settings(self) -> None:
        if not self.settings.email_enabled:
            raise RuntimeError("email is disabled")
        required = [
            self.settings.smtp_host,
            self.settings.smtp_username,
            self.settings.smtp_password,
            self.settings.smtp_from_email,
        ]
        if not all(required):
            raise RuntimeError("smtp settings are incomplete")

    def _build_message(
        self,
        *,
        to_email: str,
        subject: str,
        text_content: str,
        html_content: str | None,
    ) -> EmailMessage:
        message = EmailMessage()
        message["Subject"] = subject
        message["From"] = formataddr((self.settings.smtp_from_name, self.settings.smtp_from_email))
        message["To"] = to_email
        message.set_content(text_content)
        if html_content:
            message.add_alternative(html_content, subtype="html")
        return message

    def _send(self, message: EmailMessage) -> None:
        host = self.settings.smtp_host or ""
        port = self.settings.smtp_port
        if self.settings.smtp_use_ssl:
            with smtplib.SMTP_SSL(host, port, timeout=20) as client:
                self._login_and_send(client, message)
            return
        with smtplib.SMTP(host, port, timeout=20) as client:
            if self.settings.smtp_use_starttls:
                client.starttls()
            self._login_and_send(client, message)

    def _login_and_send(self, client: smtplib.SMTP, message: EmailMessage) -> None:
        client.login(self.settings.smtp_username or "", self.settings.smtp_password or "")
        client.send_message(message)


def _elapsed_ms(start: float) -> int:
    return int((time.perf_counter() - start) * 1000)
