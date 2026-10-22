"""お知らせメールを Gmail から送る。

送り元の Gmail アドレスとアプリパスワードは、管理者が画面で設定し、Windows の資格情報マネージャーに保存する
（ファイル・Git・画面には残さない）。例外の文面にはアドレスなどが含まれうるので、呼び出し側は種類だけを記録する。
"""

import re
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr

import keyring
from keyring.errors import PasswordDeleteError

SERVICE = "practice-room-mailer"
SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 465
SMTP_TIMEOUT_SECONDS = 20
SENDER_NAME = "練習室予約"
# 宛先に使ってよいアドレスの形（ヘッダーに入れるので、空白や改行を含むものは受け付けない）
EMAIL_PATTERN = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")


def address_problem(address: str) -> str | None:
    if len(address) > 254 or not EMAIL_PATTERN.match(address):
        return "メールアドレスの形が正しくありません"
    return None


def normalize_app_password(app_password: str) -> str:
    """Google が4文字ずつ区切って表示するアプリパスワードの空白を除く。"""
    return "".join(app_password.split())


def sender() -> str | None:
    """設定済みの送り元アドレス。未設定なら None。"""
    address = keyring.get_password(SERVICE, "address")
    return address if address and keyring.get_password(SERVICE, "app_password") else None


def configured() -> bool:
    return sender() is not None


def store(address: str, app_password: str) -> None:
    keyring.set_password(SERVICE, "address", address)
    keyring.set_password(SERVICE, "app_password", normalize_app_password(app_password))


def delete() -> None:
    for key in ("address", "app_password"):
        try:
            keyring.delete_password(SERVICE, key)
        except PasswordDeleteError:
            pass


def build_message(sender_address: str, to: str, subject: str, body: str) -> EmailMessage:
    if problem := address_problem(to):
        raise ValueError(problem)
    message = EmailMessage()
    message["From"] = formataddr((SENDER_NAME, sender_address))
    message["To"] = to
    message["Subject"] = subject
    message.set_content(body)
    return message


def send(to: str, subject: str, body: str, sender_address: str | None = None, app_password: str | None = None) -> None:
    """メールを1通送る。送り元を渡さなければ、保存した設定を使う。失敗したら例外を出す。"""
    if sender_address is None:
        sender_address = keyring.get_password(SERVICE, "address")
        app_password = keyring.get_password(SERVICE, "app_password")
        if not sender_address or not app_password:
            raise RuntimeError("お知らせメールの送り元が設定されていません")
    message = build_message(sender_address, to, subject, body)
    with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=SMTP_TIMEOUT_SECONDS,
                          context=ssl.create_default_context()) as smtp:
        smtp.login(sender_address, normalize_app_password(app_password))
        smtp.send_message(message)
