"""予約係：PCで動かしたままにして、全員の「予約係に任せた」予定を、予約可能日時に自動で予約する。

  python scheduler.py

- 30秒ごとに予定を見て、予約可能日時の10分前になった予定ごとに auto_reserve.py --unattended を起動する。
  起動された側は、予約可能日時の3分前にログインし、時刻になったら予約する（Edgeは画面に出さない）。
- 1つの予定につき1回だけ試す。結果は予定に記録され、画面の一覧に表示される。
- 実行のようすは data/logs/予定番号.log に残す（ログイン情報は書かない）。
- 止めるときは Ctrl + C（実行中の自動予約はそのまま最後まで動く）。
"""

import os
import subprocess
import sys
import time as clock
from datetime import date, datetime, time, timedelta
from pathlib import Path

from booking_rules import TOKYO, booking_opens_at, end_datetime, start_datetime
from plans_store import (
    AUTO_QUEUED,
    AUTO_RUNNING,
    STATUS_PLANNED,
    load_plans,
    scheduler_last_seen,
    set_auto,
    write_heartbeat,
)

APP_DIR = Path(__file__).parent
LOG_DIR = APP_DIR / "data" / "logs"
POLL_SECONDS = 30
LAUNCH_BEFORE_OPEN = timedelta(minutes=10)
# 「動いている印」がこれより新しければ、ほかの予約係が動いているとみなす
ALREADY_RUNNING_WINDOW = timedelta(seconds=POLL_SECONDS * 3)


def opens_at(plan: dict) -> datetime:
    start_at = start_datetime(date.fromisoformat(plan["use_date"]), time.fromisoformat(plan["start"]))
    return booking_opens_at(end_datetime(start_at, plan["duration_min"]))


def due_plans(plans: list[dict], now: datetime) -> list[dict]:
    """今起動すべき予定：予約係に任されていて、まだ予約完了でなく、予約可能日時の10分前を過ぎたもの。"""
    return [
        p
        for p in plans
        if p.get("auto") is AUTO_QUEUED and p["status"] == STATUS_PLANNED and now >= opens_at(p) - LAUNCH_BEFORE_OPEN
    ]


def launch(plan: dict) -> subprocess.Popen:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log = open(LOG_DIR / f"{plan['id']}.log", "a", encoding="utf-8")
    return subprocess.Popen(
        [sys.executable, "-u", str(APP_DIR / "auto_reserve.py"), "--plan-id", plan["id"], "--unattended"],
        cwd=APP_DIR,
        stdout=log,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
        # ログを UTF-8 で書く（Windows の初期設定の文字コードだと、Get-Content -Encoding UTF8 で文字化けする）
        env={**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"},
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )


def tick(now: datetime, running: dict) -> None:
    write_heartbeat(now)
    for plan_id, proc in list(running.items()):
        if proc.poll() is not None:
            print(f"{now:%m/%d %H:%M:%S} 予定 {plan_id} の自動予約が終わりました。")
            del running[plan_id]
    for plan in due_plans(load_plans(), now):
        if plan["id"] in running:
            # 取り消し→任せ直しのとき、前の自動予約がまだ動いていれば、終わるまで新しく始めない（二重予約を防ぐ）
            continue
        # 先に「実行中」にしてから起動する（二重に起動しないように）
        if set_auto(plan["id"], AUTO_RUNNING):
            running[plan["id"]] = launch(plan)
            print(f"{now:%m/%d %H:%M:%S} {plan.get('owner', '')} の予定 {plan['id']}（{plan['use_date']} {plan['start']}）の自動予約を始めました。")


def already_running(now: datetime) -> bool:
    """ほかの予約係が動いているか（2つ動くと、同じ予定を二重に予約するおそれがある）。"""
    last_seen = scheduler_last_seen()
    return last_seen is not None and now - last_seen < ALREADY_RUNNING_WINDOW


def main() -> None:
    if already_running(datetime.now(TOKYO)):
        raise SystemExit(
            "予約係はすでに動いています（PCの起動時に自動で始まった予約係がある可能性があります）。"
            "このウィンドウは閉じて構いません。止めたばかりのときは、2分ほど待ってから起動し直してください。"
        )
    print("予約係を始めました。このウィンドウは閉じずに、PCをスリープさせないでください。止めるときは Ctrl + C。")
    running: dict[str, subprocess.Popen] = {}
    while True:
        tick(datetime.now(TOKYO), running)
        clock.sleep(POLL_SECONDS)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("予約係を止めました。")
