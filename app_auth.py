"""予定登録の画面のパスワード（スマホなど PC 以外から開くときの鍵）。

パスワードそのものは保存せず、ソルト付きハッシュだけを data/auth.json（Git対象外）に保存する。

  python app_auth.py set   … パスワードを設定・変更する（入力しても表示されない）
"""

import hashlib
import hmac
import json
import secrets
import sys
from getpass import getpass
from pathlib import Path

AUTH_FILE = Path(__file__).parent / "data" / "auth.json"
ITERATIONS = 200_000
MIN_LENGTH = 8


def _hash(password: str, salt: bytes) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, ITERATIONS).hex()


def is_configured() -> bool:
    return AUTH_FILE.exists()


def set_password(password: str) -> None:
    if len(password) < MIN_LENGTH:
        raise ValueError(f"パスワードは{MIN_LENGTH}文字以上にしてください")
    salt = secrets.token_bytes(16)
    AUTH_FILE.parent.mkdir(exist_ok=True)
    AUTH_FILE.write_text(json.dumps({"salt": salt.hex(), "hash": _hash(password, salt)}), encoding="utf-8")


def verify(password: str) -> bool:
    if not is_configured():
        return False
    stored = json.loads(AUTH_FILE.read_text(encoding="utf-8"))
    return hmac.compare_digest(_hash(password, bytes.fromhex(stored["salt"])), stored["hash"])


def main() -> None:
    if sys.argv[1:] != ["set"]:
        raise SystemExit("使い方：python app_auth.py set")
    password = getpass(f"画面のパスワード（{MIN_LENGTH}文字以上・入力しても表示されません）：")
    if getpass("もう一度入力してください：") != password:
        raise SystemExit("2回の入力が一致しません。設定していません。")
    try:
        set_password(password)
    except ValueError as e:
        raise SystemExit(f"{e}。設定していません。") from None
    print("画面のパスワードを設定しました。")


if __name__ == "__main__":
    main()
