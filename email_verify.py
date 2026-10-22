"""お知らせメールの宛先を確かめる確認番号（6桁）。番号そのものは保存せず、ハッシュだけを設定に保存する。"""

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta

CODE_VALID = timedelta(minutes=30)
MAX_TRIES = 5


def new_code() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


def _hash(code: str) -> str:
    return hashlib.sha256(code.encode("ascii")).hexdigest()


def pending_for(address: str, code: str, now: datetime) -> dict:
    """設定に保存する「確認待ち」の内容。"""
    return {"address": address, "code_hash": _hash(code), "expires_at": (now + CODE_VALID).isoformat(), "tries": 0}


def check(pending: dict | None, code: str, now: datetime) -> tuple[bool, str | None]:
    """確認番号が合っているか。(合っているか, 合っていないときの理由)。呼び出し側は tries を1増やして保存する。"""
    if not pending:
        return False, "確認番号を送ってから入れてください。"
    if now > datetime.fromisoformat(pending["expires_at"]):
        return False, "確認番号の期限（30分）が切れました。もう一度送ってください。"
    if pending.get("tries", 0) >= MAX_TRIES:
        return False, "確認番号を続けて間違えたため、この番号は使えません。もう一度送ってください。"
    code = code.strip()
    if not code.isdigit() or not hmac.compare_digest(_hash(code), pending["code_hash"]):
        return False, "確認番号が違います。"
    return True, None
