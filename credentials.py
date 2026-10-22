"""予約サイトのログインID・パスワードを Windows の資格情報マネージャーに、人ごとに分けて保存・取得・削除する。

ファイルやGitには書かない。画面にも表示しない。
ユーザー名を指定しないときは、複数人対応の前から使っている（本人1人用の）保存場所を使う。

  python credentials.py save [ユーザー名]    … 保存（パスワードは入力しても表示されない）
  python credentials.py delete [ユーザー名]  … 削除
"""

import sys
from getpass import getpass

import keyring
from keyring.errors import PasswordDeleteError

SERVICE = "practice-room-reservation-engine"
KEYS = ("login_id", "password")


def service_for(user: str | None) -> str:
    return f"{SERVICE}:{user}" if user else SERVICE


def has(user: str | None) -> bool:
    service = service_for(user)
    return bool(keyring.get_password(service, "login_id") and keyring.get_password(service, "password"))


def load(user: str | None = None) -> tuple[str, str]:
    service = service_for(user)
    login_id = keyring.get_password(service, "login_id")
    password = keyring.get_password(service, "password")
    if not login_id or not password:
        who = f"{user} の" if user else ""
        raise SystemExit(f"{who}予約サイトのログイン情報が保存されていません。画面の「予約サイトのログイン情報」で保存してください。")
    return login_id, password


def store(user: str | None, login_id: str, password: str) -> None:
    login_id = login_id.strip()
    if not login_id or not password:
        raise ValueError("ログインIDとパスワードの両方を入力してください")
    service = service_for(user)
    keyring.set_password(service, "login_id", login_id)
    keyring.set_password(service, "password", password)


def delete(user: str | None = None) -> None:
    for key in KEYS:
        try:
            keyring.delete_password(service_for(user), key)
        except PasswordDeleteError:
            pass


def rename(old: str, new: str) -> None:
    """ユーザー名を変えたときに、保存したログイン情報を新しい名前の保存場所に移す。"""
    if has(old):
        store(new, *load(old))
        delete(old)


def copy_legacy_to(user: str) -> bool:
    """本人1人用の保存場所にあるログイン情報を、そのユーザーの保存場所に写す（まだないときだけ）。"""
    if has(user) or not has(None):
        return False
    store(user, *load(None))
    return True


def main() -> None:
    if len(sys.argv) not in (2, 3) or sys.argv[1] not in ("save", "delete"):
        raise SystemExit("使い方：python credentials.py save [ユーザー名]  または  python credentials.py delete [ユーザー名]")
    user = sys.argv[2] if len(sys.argv) == 3 else None
    if sys.argv[1] == "delete":
        delete(user)
        print("保存していたログイン情報を削除しました。")
        return
    try:
        store(user, input("ログインID："), getpass("パスワード（入力しても表示されません）："))
    except ValueError as e:
        raise SystemExit(f"{e}。保存していません。") from None
    print("Windowsの資格情報マネージャーに保存しました。")


if __name__ == "__main__":
    main()
