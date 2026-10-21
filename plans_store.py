"""登録した予定の保存と読み出し（data/plans.json。Git対象外）。画面と自動予約の両方から使う。"""

import json
import uuid
from datetime import date, datetime
from pathlib import Path

DATA_FILE = Path(__file__).parent / "data" / "plans.json"
SETTINGS_FILE = Path(__file__).parent / "data" / "settings.json"

# 画面で変えられる設定の初期値
DEFAULT_SETTINGS = {
    "favorite_rooms": [],  # 個人練習で先に試す3階の部屋（この順）
    "skip_confirm": False,  # True なら「登録」を押す前の確認をしない（全自動）
}

STATUS_PLANNED = "予定（未予約）"
STATUS_BOOKED = "予約完了"


def load_plans() -> list[dict]:
    if not DATA_FILE.exists():
        return []
    plans = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    upgraded = False
    for p in plans:
        if "id" not in p:  # 以前の版で登録した予定にも番号を付けて保存する
            p["id"] = new_id()
            upgraded = True
        if p.get("status", "").startswith(STATUS_BOOKED) and p["status"] != STATUS_BOOKED:
            p["status"] = STATUS_BOOKED
            upgraded = True
    if upgraded:
        save_plans(plans)
    return plans


def save_plans(plans: list[dict]) -> None:
    DATA_FILE.parent.mkdir(exist_ok=True)
    DATA_FILE.write_text(json.dumps(plans, ensure_ascii=False, indent=2), encoding="utf-8")


def new_id() -> str:
    return uuid.uuid4().hex[:8]


def find_plan(plans: list[dict], plan_id: str) -> dict:
    for p in plans:
        if p["id"] == plan_id:
            return p
    raise SystemExit(f"予定 {plan_id} が見つかりません。画面で削除された可能性があります。")


def booked_minutes_on(plans: list[dict], use_date: date, exclude_id: str | None = None) -> int:
    """同じ利用日の「予約完了」の予定の合計時間（分）。"""
    return sum(
        p["duration_min"]
        for p in plans
        if p["use_date"] == use_date.isoformat() and p["status"] == STATUS_BOOKED and p["id"] != exclude_id
    )


def mark_booked(plan_id: str, room: str, by: str) -> None:
    """予約完了に切り替える。自動予約の実行中に画面で編集されていてもよいように、読み直してから書く。"""
    plans = load_plans()
    plan = find_plan(plans, plan_id)
    plan["status"] = STATUS_BOOKED
    plan["booked_room"] = room
    plan["booked_by"] = by
    save_plans(plans)


def record_run(plan_id: str, at: datetime, result: str, full_rooms: list[str]) -> None:
    """自動予約を実行した結果を予定に記録する（最新の1回分）。予定が削除されていたら何もしない。"""
    plans = load_plans()
    for plan in plans:
        if plan["id"] == plan_id:
            plan["last_run"] = {"at": at.strftime("%Y-%m-%d %H:%M:%S"), "result": result, "full_rooms": full_rooms}
            save_plans(plans)
            return


def load_settings() -> dict:
    if not SETTINGS_FILE.exists():
        return dict(DEFAULT_SETTINGS)
    return {**DEFAULT_SETTINGS, **json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))}


def save_settings(settings: dict) -> None:
    SETTINGS_FILE.parent.mkdir(exist_ok=True)
    SETTINGS_FILE.write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8")
