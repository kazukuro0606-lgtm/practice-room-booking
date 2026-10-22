"""予約係：PCで動かしたままにして、全員の「予約係に任せた」予定を、予約可能日時に自動で予約する。

  python scheduler.py

- 30秒ごとに予定を見て、予約可能日時の10分前になった予定ごとに auto_reserve.py --unattended を起動する。
  起動された側は、予約可能日時の3分前にログインし、時刻になったら予約する（Edgeは画面に出さない）。
- 1つの予定につき1回だけ試す。結果は予定に記録され、画面の一覧に表示される。
- 実行のようすは data/logs/予定番号.log に残す（ログイン情報は書かない）。
- 予約サイトのログイン情報を保存した人（確認待ちの人）ごとに account_check.py を起動し、
  ログインできるか・その人に見える部屋を確かめる（ログは data/logs/check-ユーザー名.log）。
- 止めるときは Ctrl + C（実行中の自動予約はそのまま最後まで動く）。
- git pull などでこのフォルダの .py が新しくなったら、実行中の自動予約がなく、すぐ始まる予定もないときに、
  新しいコードを読み込めることを確かめてから終了コード 3 で終わる。start.ps1 は終了コード 3 なら起動し直す。
  requirements.txt が変わったときは起動し直さず、画面で管理者に知らせる（部品を入れ直す必要があるため）。
"""

import hashlib
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
    clear_heartbeat,
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
# 新しいコードで起動し直すときの終了コード（start.ps1 がこれを見て起動し直す）
RESTART_EXIT_CODE = 3
# 自動予約の起動がこの時間内に控えているあいだは、起動し直さない
RESTART_QUIET = timedelta(minutes=15)
# 起動し直す前に、新しいコードを読み込めるか確かめるモジュール
RESTART_IMPORT_CHECK = "import scheduler, auto_reserve, account_check"

# 更新の状態（restart_decision の結果）
UPDATE_NONE = "none"  # 起動したときのコードのまま
UPDATE_SETTLING = "settling"  # ファイルが書き換わっている途中かもしれないので、もう1回待つ
UPDATE_BUSY = "busy"  # 自動予約の実行中、またはすぐ始まる予定があるので待つ
UPDATE_NEEDS_INSTALL = "needs_install"  # requirements.txt が変わった。部品を入れ直してから手で起動し直す
UPDATE_RESTART = "restart"  # 今起動し直してよい


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


def tick(now: datetime, running: dict, note: str = "") -> None:
    write_heartbeat(now, note)
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


def code_fingerprint(directory: Path = APP_DIR) -> str:
    """このフォルダの .py（テストを除く）の中身の印。ファイルが新しくなると変わる。"""
    digest = hashlib.sha256()
    for path in sorted(directory.glob("*.py")):
        if not path.name.startswith("test_"):
            digest.update(path.name.encode("utf-8") + b"\0" + path.read_bytes() + b"\0")
    return digest.hexdigest()


def requirements_fingerprint(directory: Path = APP_DIR) -> str:
    path = directory / "requirements.txt"
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else ""


def launch_soon(plans: list[dict], now: datetime) -> bool:
    """RESTART_QUIET 以内に起動する予定があるか。"""
    return any(
        p.get("auto") is AUTO_QUEUED and p["status"] == STATUS_PLANNED
        and opens_at(p) - LAUNCH_BEFORE_OPEN <= now + RESTART_QUIET
        for p in plans
    )


def restart_decision(started: str, previous: str, current: str, requirements_changed: bool, busy: bool) -> str:
    """新しいコードで起動し直すかどうか。

    started は起動したとき、previous は前回見たとき、current は今のコードの印。
    """
    if requirements_changed:
        return UPDATE_NEEDS_INSTALL
    if current == started:
        return UPDATE_NONE
    if current != previous:
        return UPDATE_SETTLING
    if busy:
        return UPDATE_BUSY
    return UPDATE_RESTART


def new_code_loads() -> bool:
    """新しいコードを別のプロセスで読み込んでみる（書き間違いがあれば、起動し直さずに今のコードで動き続ける）。"""
    try:
        result = subprocess.run([sys.executable, "-c", RESTART_IMPORT_CHECK], cwd=APP_DIR, capture_output=True,
                                timeout=120, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except Exception:
        return False
    return result.returncode == 0


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
    started = previous = code_fingerprint()
    started_requirements = requirements_fingerprint()
    failed = None  # 読み込めなかった新しいコードの印（同じものを何度も試さない）
    note = ""
    while True:
        now = datetime.now(TOKYO)
        tick(now, running, note)
        current = code_fingerprint()
        decision = restart_decision(started, previous, current, requirements_fingerprint() != started_requirements,
                                    busy=bool(running) or launch_soon(load_plans(), now))
        previous = current
        if decision == UPDATE_NEEDS_INSTALL:
            note = ("新しい版で必要な部品が変わりました。予約係と画面を止め、"
                    "`.venv\\Scripts\\python.exe -m pip install -r requirements.txt` を実行してから start.ps1 で起動し直してください。")
        elif decision == UPDATE_RESTART and current != failed:
            if new_code_loads():
                print(f"{now:%m/%d %H:%M:%S} 新しい版になったので、予約係を起動し直します。")
                clear_heartbeat()
                raise SystemExit(RESTART_EXIT_CODE)
            failed = current
            note = "新しい版を読み込めなかったため、予約係は前の版のまま動いています。管理者は予約係のウィンドウで python scheduler.py を実行して、表示を確かめてください。"
            print(f"{now:%m/%d %H:%M:%S} {note}")
        elif decision == UPDATE_NONE:
            note = ""
        write_heartbeat(now, note)  # お知らせが変わったら、次の30秒を待たずに画面へ出す
        clock.sleep(POLL_SECONDS)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        # 止めたらすぐ起動し直せるように「動いている印」を消す（ウィンドウを閉じたときは消せないので、2分ほど待つ）
        clear_heartbeat()
        print("予約係を止めました。")
