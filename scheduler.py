"""予約係：PCで動かしたままにして、全員の「予約係に任せた」予定を、予約可能日時に自動で予約する。

  python scheduler.py

- 30秒ごとに予定を見て、予約可能日時の10分前になった予定ごとに auto_reserve.py --unattended を起動する。
  起動された側は、予約可能日時の3分前にログインし、時刻になったら予約する（Edgeは画面に出さない）。
- 1つの予定につき1回だけ試す。結果は予定に記録され、画面の一覧に表示される。
- 実行のようすは data/logs/予定番号.log に残す（ログイン情報は書かない）。
- 予約サイトのログイン情報を保存した人（確認待ちの人）ごとに account_check.py を起動し、
  ログインできるか・その人に見える部屋を確かめる（ログは data/logs/check-ユーザー名.log）。
- 止めるときは Ctrl + C（実行中の自動予約はそのまま最後まで動く）。
"""

import os
import subprocess
import sys
import time as clock
from datetime import date, datetime, time, timedelta
from pathlib import Path

import app_auth
import credentials
from account_checks import STATUS_RUNNING, needs_check, save_check
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


def _spawn(args: list[str], log_name: str) -> subprocess.Popen:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log = open(LOG_DIR / log_name, "a", encoding="utf-8")
    return subprocess.Popen(
        [sys.executable, "-u", *args],
        cwd=APP_DIR,
        stdout=log,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
        # ログを UTF-8 で書く（Windows の初期設定の文字コードだと、Get-Content -Encoding UTF8 で文字化けする）
        env={**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"},
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )


def launch(plan: dict) -> subprocess.Popen:
    return _spawn([str(APP_DIR / "auto_reserve.py"), "--plan-id", plan["id"], "--unattended"], f"{plan['id']}.log")


def launch_check(user: str) -> subprocess.Popen:
    return _spawn([str(APP_DIR / "account_check.py"), "--user", user], f"check-{user}.log")


def users_to_check() -> list[str]:
    """予約サイトのログイン情報を保存していて、アカウントの確認がまだの人。"""
    return [u for u in app_auth.list_users() if needs_check(u) and credentials.has(u)]


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
    for user in users_to_check():
        key = f"check:{user}"
        if key in running:
            continue  # 前の確認がまだ動いている
        save_check(user, {"status": STATUS_RUNNING})
        running[key] = launch_check(user)
        print(f"{now:%m/%d %H:%M:%S} {user} の予約サイトのアカウントを確かめ始めました。")


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
