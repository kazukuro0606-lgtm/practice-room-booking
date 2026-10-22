"""自動予約の結果を、予定を登録した本人にメールで知らせる（お知らせメールを登録した人だけ）。

メールに書くのは、日時・部屋・結果だけ。学籍番号・ログイン情報は書かない。
"""

from datetime import date

import mailer
from plans_store import STATUS_BOOKED, find_plan, load_plans, load_settings

WEEKDAYS = "月火水木金土日"


def _when(plan: dict) -> str:
    day = date.fromisoformat(plan["use_date"])
    return f"{day.month}/{day.day}（{WEEKDAYS[day.weekday()]}）{plan['start']}〜{plan['end']}"


def result_message(plan: dict) -> tuple[str, str]:
    """(件名, 本文)。"""
    result = plan.get("last_run", {}).get("result", "")
    when = _when(plan)
    if plan.get("status") == STATUS_BOOKED and plan.get("booked_room"):
        subject = f"【練習室】予約完了 {when} {plan['booked_room']}"
        lines = [
            "練習室の自動予約が完了しました。",
            "",
            f"日時：{when}",
            f"部屋：{plan['booked_room']}",
            "",
            "念のため、予約サイトの「予約内容」でも確かめてください。",
            "予定が変わったら、すぐにキャンセルしてください。",
        ]
    else:
        subject = f"【練習室】予約できませんでした {when}"
        lines = [
            "練習室の自動予約ができませんでした。",
            "",
            f"日時：{when}",
            f"結果：{result}",
            "",
            "別の日時・部屋で登録し直すか、予約サイトで直接予約してください。",
        ]
    lines += ["", "（このメールは練習室予約のアプリから自動で送っています。届かないようにするには、アプリの「お知らせメール」で登録を取り消してください）"]
    return subject, "\n".join(lines)


def notify_plan_result(plan_id: str) -> None:
    """予定の最新の結果を知らせる。メールが送れなくても予約の処理には影響させない（失敗は種類だけ表示する）。"""
    try:
        plan = find_plan(load_plans(), plan_id)
        if "last_run" not in plan or not plan.get("owner"):
            return
        address = load_settings(plan["owner"]).get("email")
        if not address or not mailer.configured():
            return
        mailer.send(address, *result_message(plan))
        print("結果をお知らせメールで送りました。")
    except SystemExit:
        return  # 予定が削除されていた
    except Exception as e:
        print(f"お知らせメールを送れませんでした（{type(e).__name__}）。")
