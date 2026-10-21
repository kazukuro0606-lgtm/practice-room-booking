"""予定登録の画面のアカウント（ユーザー名＋パスワード）。

パスワードそのものは保存せず、ソルト付きハッシュだけを data/users.json（Git対象外）に保存する。
最初の管理者は PC の PowerShell で作り、友達のアカウントは管理者が画面から作る。

  python app_auth.py add-admin ユーザー名   … 管理者を作る（パスワードは入力しても表示されない）
  python app_auth.py reset ユーザー名       … パスワードを設定し直す
"""

import hashlib
import hmac
import json
import re
import secrets
import sys
from getpass import getpass
from pathlib import Path

USERS_FILE = Path(__file__).parent / "data" / "users.json"
ITERATIONS = 200_000
MIN_LENGTH = 8
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


def _record(password: str, is_admin: bool) -> dict:
    if len(password) < MIN_LENGTH:
        raise ValueError(f"パスワードは{MIN_LENGTH}文字以上にしてください")
    salt = secrets.token_bytes(16)
    return {"salt": salt.hex(), "hash": _hash(password, salt), "is_admin": is_admin}


def has_users() -> bool:
    return bool(_load())


def list_users() -> list[str]:
    return sorted(_load())


def is_admin(username: str) -> bool:
    return _load().get(username, {}).get("is_admin", False)


def add_user(username: str, password: str, is_admin: bool = False) -> None:
    if not USERNAME_PATTERN.match(username):
        raise ValueError("ユーザー名は英小文字・数字・_・- の2〜20文字にしてください")
    users = _load()
    if username in users:
        raise ValueError(f"{username} はすでにあります")
    users[username] = _record(password, is_admin)
    _save(users)


def set_password(username: str, password: str) -> None:
    users = _load()
    if username not in users:
        raise ValueError(f"{username} というアカウントはありません")
    users[username] = _record(password, users[username]["is_admin"])
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
