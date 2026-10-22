"""予約サイトのアカウントの確認結果（data/account_checks/ユーザー名.json。Git対象外）。

予約サイトのログイン情報を保存すると「確認待ち」になり、予約係（scheduler.py）が account_check.py で確かめる：
- そのログインIDとパスワードでログインできるか
- その人に見える部屋（予約サイトはコースによって見せる部屋が違う。見える部屋＝その人が使ってよい部屋）
- 見える部屋のうち、このアプリに未登録の部屋の予約画面の作り（管理者が見て、部屋を登録するか決める）
"""

import json
from datetime import datetime
from pathlib import Path

CHECK_DIR = Path(__file__).parent / "data" / "account_checks"

STATUS_QUEUED = "queued"  # 確認待ち
STATUS_RUNNING = "running"  # 予約係が確認中
STATUS_OK = "ok"  # ログインでき、見える部屋が分かった
STATUS_LOGIN_FAILED = "login_failed"  # ログインできなかった
STATUS_ERROR = "error"  # 予約サイトが開けない等で、確かめられなかった


def _path(user: str) -> Path:
    return CHECK_DIR / f"{user}.json"


def load_check(user: str) -> dict | None:
    path = _path(user)
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def save_check(user: str, check: dict) -> None:
    CHECK_DIR.mkdir(parents=True, exist_ok=True)
    _path(user).write_text(json.dumps(check, ensure_ascii=False, indent=2), encoding="utf-8")


def request_check(user: str) -> None:
    """確認待ちにする（ログイン情報を保存し直したとき・もう一度確かめるとき）。"""
    save_check(user, {"status": STATUS_QUEUED})


def delete_check(user: str) -> None:
    _path(user).unlink(missing_ok=True)


def needs_check(user: str) -> bool:
    """予約係が確認を始めるべきか（まだ確認していない・確認待ち）。"""
    check = load_check(user)
    return check is None or check.get("status") == STATUS_QUEUED


def record_result(user: str, at: datetime, status: str, visible: dict[str, int] | None = None,
                  unknown: dict[str, dict] | None = None, message: str = "") -> None:
    save_check(user, {
        "status": status,
        "checked_at": at.strftime("%Y-%m-%d %H:%M:%S"),
        "visible_rooms": visible or {},
        "unknown_rooms": unknown or {},
        "message": message,
    })


def visible_rooms(user: str | None) -> set[str] | None:
    """その人に見える部屋。まだ確かめられていないときは None。"""
    if not user:
        return None
    check = load_check(user)
    if not check or check.get("status") != STATUS_OK:
        return None
    return set(check.get("visible_rooms", {}))
