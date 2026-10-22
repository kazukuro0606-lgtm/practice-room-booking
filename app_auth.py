"""予定登録の画面のアカウント（ユーザー名＋パスワード）。

パスワードそのものは保存せず、ソルト付きハッシュだけを data/users.json（Git対象外）に保存する。
最初の管理者は PC の PowerShell で作り、友達のアカウントは管理者が画面から作る。

画面をインターネットに公開しても総当たりされにくいように、
- パスワードは8文字以上で、単純なものは受け付けない（password_problem）
- ログインの失敗を data/login_attempts.json に記録し、ページを開き直しても解除されない制限をかける
  （同じユーザー名で15分に5回失敗 → 15分ロック、全体で10分に30回失敗 → 全員のログインを10分止める）

  python app_auth.py add-admin ユーザー名   … 管理者を作る（パスワードは入力しても表示されない）
  python app_auth.py reset ユーザー名       … パスワードを設定し直す
"""

import hashlib
import hmac
import json
import re
import secrets
import sys
from datetime import datetime, timedelta
from getpass import getpass
from pathlib import Path

USERS_FILE = Path(__file__).parent / "data" / "users.json"
ATTEMPTS_FILE = Path(__file__).parent / "data" / "login_attempts.json"
ITERATIONS = 200_000
MIN_LENGTH = 8  # ログインの失敗の制限（ロック）と合わせて総当たりを防ぐ
# よく使われていて推測されやすいパスワード（これを含むものは受け付けない）
COMMON_WORDS = ("password", "passw0rd", "qwerty", "123456", "654321", "abc123", "abcdefgh", "iloveyou", "senzoku", "reservation")

USER_FAIL_LIMIT = 5
USER_FAIL_WINDOW = timedelta(minutes=15)
USER_LOCK = timedelta(minutes=15)
GLOBAL_FAIL_LIMIT = 30
GLOBAL_FAIL_WINDOW = timedelta(minutes=10)
GLOBAL_LOCK = timedelta(minutes=10)
# ユーザー名は資格情報マネージャーの名前やファイル名にも使うので、英小文字・数字・_- に限る
USERNAME_PATTERN = re.compile(r"^[a-z0-9_-]{2,20}$")


def _hash(password: str, salt: bytes) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, ITERATIONS).hex()


def _load() -> dict:
    if not USERS_FILE.exists():
        return {}
    return json.loads(USERS_FILE.read_text(encoding="utf-8"))


def _save(users: dict) -> None:
    USERS_FILE.parent.mkdir(exist_ok=True)
    USERS_FILE.write_text(json.dumps(users, ensure_ascii=False, indent=2), encoding="utf-8")


def password_problem(password: str, username: str = "") -> str | None:
    """パスワードが弱いときは理由を返す。問題なければ None。"""
    lowered = password.lower()
    if len(password) < MIN_LENGTH:
        return f"パスワードは{MIN_LENGTH}文字以上にしてください"
    if len(set(password)) < 5:
        return "同じ文字の繰り返しが多すぎます"
    if password.isdigit():
        return "数字だけのパスワードは使えません"
    if username and username.lower() in lowered:
        return "ユーザー名を含むパスワードは使えません"
    if any(word in lowered for word in COMMON_WORDS):
        return "推測されやすい言葉を含むパスワードは使えません"
    return None


# 最初のパスワードに使う文字。スマホで打ち間違えやすい・見分けにくい文字（0とo、1とlとi など）は使わない
PASSWORD_CHARS = "abcdefghjkmnpqrstuvwxyz23456789"


def generate_password() -> str:
    """友達の最初のパスワードなどに使う、推測されにくく、スマホでも写しやすいパスワード（例：k7mf-2xqp-h9tw）。"""
    while True:
        password = "-".join("".join(secrets.choice(PASSWORD_CHARS) for _ in range(4)) for _ in range(3))
        if password_problem(password) is None:
            return password


def _record(username: str, password: str, is_admin: bool, must_change: bool) -> dict:
    if problem := password_problem(password, username):
        raise ValueError(problem)
    salt = secrets.token_bytes(16)
    return {"salt": salt.hex(), "hash": _hash(password, salt), "is_admin": is_admin, "must_change": must_change}


def has_users() -> bool:
    return bool(_load())


def list_users() -> list[str]:
    return sorted(_load())


def is_admin(username: str) -> bool:
    return _load().get(username, {}).get("is_admin", False)


def must_change_password(username: str) -> bool:
    """管理者が決めたパスワード（最初のパスワード・設定し直したパスワード）のままか。"""
    return _load().get(username, {}).get("must_change", False)


def username_problem(username: str) -> str | None:
    """新しく使うユーザー名に問題があるときは理由を返す。問題なければ None。"""
    if not USERNAME_PATTERN.match(username):
        return "ユーザー名は英小文字・数字・_・- の2〜20文字にしてください"
    if username in _load():
        return f"{username} はすでに使われています"
    return None


def add_user(username: str, password: str, is_admin: bool = False, must_change: bool = False) -> None:
    if problem := username_problem(username):
        raise ValueError(problem)
    users = _load()
    users[username] = _record(username, password, is_admin, must_change)
    _save(users)


def set_password(username: str, password: str, must_change: bool = False) -> None:
    users = _load()
    if username not in users:
        raise ValueError(f"{username} というアカウントはありません")
    users[username] = _record(username, password, users[username]["is_admin"], must_change)
    _save(users)


def rename_user(old: str, new: str) -> None:
    """アカウントのユーザー名を変える（パスワード・管理者かどうかはそのまま）。"""
    if problem := username_problem(new):
        raise ValueError(problem)
    users = _load()
    if old not in users:
        raise ValueError(f"{old} というアカウントはありません")
    users[new] = users.pop(old)
    _save(users)


def delete_user(username: str) -> None:
    users = _load()
    users.pop(username, None)
    _save(users)


def verify(username: str, password: str) -> bool:
    user = _load().get(username)
    if user is None:
        _hash(password, b"0" * 16)  # 存在しないユーザーでも同じくらい時間をかける
        return False
    return hmac.compare_digest(_hash(password, bytes.fromhex(user["salt"])), user["hash"])


def _load_attempts() -> list[dict]:
    if not ATTEMPTS_FILE.exists():
        return []
    return json.loads(ATTEMPTS_FILE.read_text(encoding="utf-8"))


def _save_attempts(attempts: list[dict]) -> None:
    ATTEMPTS_FILE.parent.mkdir(exist_ok=True)
    ATTEMPTS_FILE.write_text(json.dumps(attempts, ensure_ascii=False), encoding="utf-8")


def _failures(now: datetime, window: timedelta, username: str | None = None) -> list[datetime]:
    times = [
        datetime.fromisoformat(a["at"])
        for a in _load_attempts()
        if username is None or a["user"] == username
    ]
    return sorted(t for t in times if now - t < window)


def login_blocked(username: str, now: datetime) -> str | None:
    """今ログインを試せないときは、その理由を返す。"""
    everyone = _failures(now, GLOBAL_FAIL_WINDOW)
    if len(everyone) >= GLOBAL_FAIL_LIMIT:
        until = everyone[-1] + GLOBAL_LOCK
        if now < until:
            return f"ログインの失敗が続いたため、{until:%H:%M} まで全員のログインを止めています。"
    mine = _failures(now, USER_FAIL_WINDOW, username)
    if len(mine) >= USER_FAIL_LIMIT:
        until = mine[-1] + USER_LOCK
        if now < until:
            return f"このユーザー名はパスワードを続けて間違えたため、{until:%H:%M} までロックしています。"
    return None


def record_failure(username: str, now: datetime) -> None:
    keep = max(USER_FAIL_WINDOW, GLOBAL_FAIL_WINDOW, USER_LOCK, GLOBAL_LOCK)
    attempts = [a for a in _load_attempts() if now - datetime.fromisoformat(a["at"]) < keep]
    attempts.append({"user": username[:40], "at": now.isoformat()})
    _save_attempts(attempts)


def clear_failures(username: str) -> None:
    _save_attempts([a for a in _load_attempts() if a["user"] != username])


def _ask_password() -> str:
    password = getpass(f"パスワード（{MIN_LENGTH}文字以上・入力しても表示されません）：")
    if getpass("もう一度入力してください：") != password:
        raise SystemExit("2回の入力が一致しません。設定していません。")
    return password


def main() -> None:
    if len(sys.argv) != 3 or sys.argv[1] not in ("add-admin", "reset"):
        raise SystemExit("使い方：python app_auth.py add-admin ユーザー名  または  python app_auth.py reset ユーザー名")
    command, username = sys.argv[1], sys.argv[2]
    try:
        if command == "add-admin":
            add_user(username, _ask_password(), is_admin=True)
            print(f"管理者 {username} を作りました。")
        else:
            set_password(username, _ask_password())
            print(f"{username} のパスワードを設定し直しました。")
    except ValueError as e:
        raise SystemExit(f"{e}。") from None


if __name__ == "__main__":
    main()
