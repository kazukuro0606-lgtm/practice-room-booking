"""登録した予定と設定の保存と読み出し（data/。Git対象外）。画面と自動予約の両方から使う。

予定には登録した人（owner）を記録し、設定は人ごとのファイルに分ける。
"""

import json
import os
import time
import uuid
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path

DATA_FILE = Path(__file__).parent / "data" / "plans.json"
SETTINGS_DIR = Path(__file__).parent / "data" / "settings"
# 複数人対応の前の、本人1人用の設定ファイル
LEGACY_SETTINGS_FILE = Path(__file__).parent / "data" / "settings.json"

# 画面で変えられる設定の初期値
DEFAULT_SETTINGS = {
    "favorite_rooms": [],  # 個人練習で先に試す3階の部屋（この順）
    "skip_confirm": False,  # True なら「登録」を押す前の確認をしない（全自動）
    "approved_notices": [],  # 本人が承認した注意事項の印（notices.NOTICE_VERSION）
    "onboarded_version": 0,  # 同意した「はじめに」の版（onboarding.ONBOARDING_VERSION）。0 はまだ
}

STATUS_PLANNED = "予定（未予約）"
STATUS_BOOKED = "予約完了"

# 予定の "auto"：予約係（scheduler.py）に任せているか
AUTO_OFF = False  # 任せていない（または、予約係が1回試し終わった）
AUTO_QUEUED = True  # 任せた。予約可能日時が近づいたら予約係が始める
AUTO_RUNNING = "running"  # 予約係が自動予約を実行中

HEARTBEAT_FILE = Path(__file__).parent / "data" / "scheduler.json"

# 予定ファイルは、画面・予約係・自動予約（予定ごとに別のプロセス）が同時に読み書きする。
# 「読む→変える→書く」の間をロックファイルで1つずつにして、同時に終わった結果が消えないようにする。
LOCK_WAIT_SECONDS = 30
# これより古いロックファイルは、書いている途中で止まったプロセスの残りとみなして消す
LOCK_STALE_SECONDS = 60


def _lock_file() -> Path:
    return DATA_FILE.with_name(DATA_FILE.name + ".lock")


@contextmanager
def _plans_lock():
    lock = _lock_file()
    lock.parent.mkdir(exist_ok=True)
    deadline = time.monotonic() + LOCK_WAIT_SECONDS
    while True:
        try:
            os.close(os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY))
            break
        except FileExistsError:
            try:
                if time.time() - lock.stat().st_mtime > LOCK_STALE_SECONDS:
                    lock.unlink(missing_ok=True)
                    continue
            except FileNotFoundError:
                continue
            if time.monotonic() > deadline:
                raise TimeoutError("予定ファイルのロックを取れませんでした")
            time.sleep(0.05)
    try:
        yield
    finally:
        lock.unlink(missing_ok=True)


def _read() -> list[dict]:
    if not DATA_FILE.exists():
        return []
    return json.loads(DATA_FILE.read_text(encoding="utf-8"))


def _write(plans: list[dict]) -> None:
    """一時ファイルに書いてから置き換える（書きかけのファイルを読ませない）。"""
    DATA_FILE.parent.mkdir(exist_ok=True)
    tmp = DATA_FILE.with_name(DATA_FILE.name + ".tmp")
    tmp.write_text(json.dumps(plans, ensure_ascii=False, indent=2), encoding="utf-8")
    for attempt in range(20):
        try:
            os.replace(tmp, DATA_FILE)
            return
        except PermissionError:  # Windows でウイルス対策ソフトなどが一瞬開いているとき
            if attempt == 19:
                raise
            time.sleep(0.05)


def _upgrade(plans: list[dict]) -> bool:
    """以前の版で保存した予定を今の形にそろえる。変えたら True。"""
    upgraded = False
    for p in plans:
        if "id" not in p:  # 以前の版で登録した予定にも番号を付けて保存する
            p["id"] = new_id()
            upgraded = True
        if p.get("status", "").startswith(STATUS_BOOKED) and p["status"] != STATUS_BOOKED:
            p["status"] = STATUS_BOOKED
            upgraded = True
    return upgraded


def load_plans() -> list[dict]:
    with _plans_lock():
        plans = _read()
        if _upgrade(plans):
            _write(plans)
    return plans


def save_plans(plans: list[dict]) -> None:
    """予定を丸ごと書く。読み直してから変えるときは update_plans を使う。"""
    with _plans_lock():
        _write(plans)


def update_plans(change):
    """ロックしたまま予定ファイルを読み直し、change(plans) で変えて保存する。

    change は渡された一覧をその場で変えるか、新しい一覧を返す。戻り値は保存した一覧。
    """
    with _plans_lock():
        plans = _read()
        _upgrade(plans)
        result = change(plans)
        if result is not None:
            plans = result
        _write(plans)
    return plans


def new_id() -> str:
    return uuid.uuid4().hex[:8]


def find_plan(plans: list[dict], plan_id: str) -> dict:
    for p in plans:
        if p["id"] == plan_id:
            return p
    raise SystemExit(f"予定 {plan_id} が見つかりません。画面で削除された可能性があります。")


def plans_of(plans: list[dict], owner: str) -> list[dict]:
    return [p for p in plans if p.get("owner") == owner]


def booked_minutes_on(plans: list[dict], use_date: date, exclude_id: str | None = None, owner: str | None = None) -> int:
    """同じ利用日の「予約完了」の予定の合計時間（分）。owner を指定すると、その人の予定だけを数える。"""
    return sum(
        p["duration_min"]
        for p in plans
        if p["use_date"] == use_date.isoformat()
        and p["status"] == STATUS_BOOKED
        and p["id"] != exclude_id
        and (owner is None or p.get("owner") == owner)
    )


def booked_count_on(plans: list[dict], use_date: date, exclude_id: str | None = None, owner: str | None = None) -> int:
    """同じ利用日の「予約完了」の予定の数。owner を指定すると、その人の予定だけを数える。"""
    return sum(
        1
        for p in plans
        if p["use_date"] == use_date.isoformat()
        and p["status"] == STATUS_BOOKED
        and p["id"] != exclude_id
        and (owner is None or p.get("owner") == owner)
    )


def claim_legacy(admin: str) -> None:
    """複数人対応の前に登録した予定（owner なし）と設定を、管理者のものにする。"""
    if any("owner" not in p for p in load_plans()):

        def change(plans):
            for p in plans:
                p.setdefault("owner", admin)

        update_plans(change)
    if LEGACY_SETTINGS_FILE.exists() and not _settings_file(admin).exists():
        save_settings(admin, {**DEFAULT_SETTINGS, **json.loads(LEGACY_SETTINGS_FILE.read_text(encoding="utf-8"))})


def delete_user_data(owner: str) -> None:
    """アカウントを消すときに、その人の予定と設定も消す。"""
    update_plans(lambda plans: [p for p in plans if p.get("owner") != owner])
    _settings_file(owner).unlink(missing_ok=True)


def rename_owner(old: str, new: str) -> None:
    """ユーザー名を変えたときに、その人の予定と設定を新しい名前に移す。"""

    def change(plans):
        for p in plans:
            if p.get("owner") == old:
                p["owner"] = new

    update_plans(change)
    if _settings_file(old).exists():
        _settings_file(old).replace(_settings_file(new))


def mark_booked(plan_id: str, room: str, by: str) -> None:
    """予約完了に切り替える。自動予約の実行中に画面で編集されていてもよいように、読み直してから書く。"""

    def change(plans):
        plan = find_plan(plans, plan_id)
        plan["status"] = STATUS_BOOKED
        plan["booked_room"] = room
        plan["booked_by"] = by

    update_plans(change)


def record_run(plan_id: str, at: datetime, result: str, full_rooms: list[str]) -> None:
    """自動予約を実行した結果を予定に記録する（最新の1回分）。予定が削除されていたら何もしない。"""

    def change(plans):
        for plan in plans:
            if plan["id"] == plan_id:
                plan["last_run"] = {"at": at.strftime("%Y-%m-%d %H:%M:%S"), "result": result, "full_rooms": full_rooms}
                # 1つの予定につき予約係が試すのは1回。結果が出たら「任せる」状態を外す
                plan["auto"] = False

    update_plans(change)


def _settings_file(owner: str) -> Path:
    return SETTINGS_DIR / f"{owner}.json"


def set_auto(plan_id: str, value, owner: str | None = None) -> bool:
    """予定の「任せる」状態を変える。owner を指定したときは、その人の予定だけを変える。変えたら True。"""
    changed = False

    def change(plans):
        nonlocal changed
        for plan in plans:
            if plan["id"] == plan_id and (owner is None or plan.get("owner") == owner):
                plan["auto"] = value
                changed = True
                return

    update_plans(change)
    return changed


def auto_state(plan_id: str):
    for plan in load_plans():
        if plan["id"] == plan_id:
            return plan.get("auto", AUTO_OFF)
    return AUTO_OFF


def write_heartbeat(now: datetime) -> None:
    HEARTBEAT_FILE.parent.mkdir(exist_ok=True)
    HEARTBEAT_FILE.write_text(json.dumps({"last_seen": now.isoformat()}), encoding="utf-8")


def scheduler_last_seen() -> datetime | None:
    if not HEARTBEAT_FILE.exists():
        return None
    return datetime.fromisoformat(json.loads(HEARTBEAT_FILE.read_text(encoding="utf-8"))["last_seen"])


def load_settings(owner: str) -> dict:
    path = _settings_file(owner)
    if not path.exists():
        return dict(DEFAULT_SETTINGS)
    return {**DEFAULT_SETTINGS, **json.loads(path.read_text(encoding="utf-8"))}


def save_settings(owner: str, settings: dict) -> None:
    SETTINGS_DIR.mkdir(parents=True, exist_ok=True)
    _settings_file(owner).write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8")
