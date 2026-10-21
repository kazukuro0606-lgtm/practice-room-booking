"""ログインID・パスワードを Windows の資格情報マネージャーに保存・取得・削除する。

ファイルやGitには書かない。画面にも表示しない。

  python credentials.py save    … 保存（パスワードは入力しても表示されない）
  python credentials.py delete  … 削除
"""

import sys
from getpass import getpass

import keyring
from keyring.errors import PasswordDeleteError

SERVICE = "practice-room-reservation-engine"
KEYS = ("login_id", "password")


def load() -> tuple[str, str]:
    login_id = keyring.get_password(SERVICE, "login_id")
    password = keyring.get_password(SERVICE, "password")
    if not login_id or not password:
        raise SystemExit("ログイン情報が保存されていません。先に python credentials.py save を実行してください。")
    return login_id, password


def save() -> None:
    login_id = input("ログインID：").strip()
    password = getpass("パスワード（入力しても表示されません）：")
    if not login_id or not password:
        raise SystemExit("ログインIDとパスワードの両方を入力してください。保存していません。")
    keyring.set_password(SERVICE, "login_id", login_id)
    keyring.set_password(SERVICE, "password", password)
    print("Windowsの資格情報マネージャーに保存しました。")


def delete() -> None:
    for key in KEYS:
        try:
            keyring.delete_password(SERVICE, key)
        except PasswordDeleteError:
            pass
    print("保存していたログイン情報を削除しました。")


if __name__ == "__main__":
    commands = {"save": save, "delete": delete}
    if len(sys.argv) != 2 or sys.argv[1] not in commands:
        raise SystemExit("使い方：python credentials.py save  または  python credentials.py delete")
    commands[sys.argv[1]]()
