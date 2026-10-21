"""練習室の予約予定を登録する画面（PC内 localhost だけで動く）。

この画面自体は大学サイトに接続しない。
「自動予約を起動」を押したときだけ、別ウィンドウで auto_reserve.py を起動する。
"""

import subprocess
import sys
from datetime import date, time
from pathlib import Path

import streamlit as st

from booking_rules import (
    DAILY_LIMIT_MIN,
    DURATION_CHOICES_MIN,
    PRACTICE_ENSEMBLE,
    PRACTICE_SOLO,
    ROOM_3F,
    ROOM_MAX_MIN,
    ROOM_TB,
    check_plan,
)
from plans_store import STATUS_BOOKED, STATUS_PLANNED, booked_minutes_on, load_plans, new_id, save_plans

APP_DIR = Path(__file__).parent
ROOMS = [ROOM_3F, ROOM_TB]
PRACTICE_TYPES = [PRACTICE_SOLO, PRACTICE_ENSEMBLE]


def duration_label(minutes: int) -> str:
    hours, rest = divmod(minutes, 60)
    return "".join([f"{hours}時間" if hours else "", f"{rest}分" if rest else ""])


def fmt(dt) -> str:
    return dt.strftime("%Y-%m-%d %H:%M")


def launch_auto_reserve(plan_id: str) -> None:
    """自動予約を新しいPowerShell（コンソール）ウィンドウで起動する。"""
    subprocess.Popen(
        [sys.executable, str(APP_DIR / "auto_reserve.py"), "--plan-id", plan_id],
        cwd=APP_DIR,
        creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0),
    )


st.set_page_config(page_title="練習室予約の予定", page_icon="🎵")
st.title("練習室予約の予定登録")
st.caption("自分のログインID・パスワードはここに入力しないでください（資格情報マネージャーに保存したものを使います）。")

st.header("1. 予定を入力")
use_date = st.date_input("利用日", value=date.today())
start_time = st.time_input("開始時刻", value=time(15, 0), step=1800)
duration = st.radio("利用時間", DURATION_CHOICES_MIN, format_func=duration_label, horizontal=True)
practice_type = st.radio("練習の種類", PRACTICE_TYPES, horizontal=True)
room = st.selectbox("希望する部屋", ROOMS)
members_text = ""
if room == ROOM_TB:
    members_text = st.text_area(
        "同時利用者の学籍番号（1行に1人・TBの部屋では必須）",
        help="このPCの data/plans.json にだけ保存します。一緒に使う人には、予約に使うことを伝えておいてください。",
    )
members = [m.strip() for m in members_text.splitlines() if m.strip()]
equipment = st.text_input("設備条件（任意）", placeholder="例：ピアノあり、譜面台2台")
existing = st.number_input(
    "このアプリの外で取った、同じ利用日の予約時間（分）",
    min_value=0,
    max_value=1440,
    value=0,
    step=30,
    help="このアプリで「予約完了」になっている予定の時間は、自動で合計に入ります。",
)

plans = load_plans()
booked_in_app = booked_minutes_on(plans, use_date)
check = check_plan(use_date, start_time, duration, int(existing) + booked_in_app, practice_type, room)

st.header("2. 確認")
st.write(f"利用時間：{use_date:%Y-%m-%d} {start_time:%H:%M} 〜 {fmt(check.end_at)}（Asia/Tokyo）")
st.info(f"予約可能になる日時：**{fmt(check.opens_at)}**（利用終了の7日前）")
st.write(
    f"この日の合計：アプリ外 {int(existing)}分 ＋ アプリで予約完了 {booked_in_app}分 ＋ 希望 {duration}分"
    f" ＝ **{check.daily_total_min}分**"
)
if check.over_daily_limit:
    st.warning(f"この日の合計が{DAILY_LIMIT_MIN}分を超えています。この予定は自動予約できません。")
if check.room_advice:
    st.warning(check.room_advice)
if check.over_room_limit:
    st.error(f"{room}は{duration_label(ROOM_MAX_MIN[room])}までしか予約できません。")
if room == ROOM_TB and not members:
    st.error("TBの部屋では、同時利用者の学籍番号が必要です。")

can_register = not check.over_room_limit and not (room == ROOM_TB and not members)
if st.button("予定として登録する", disabled=not can_register):
    plans.append(
        {
            "id": new_id(),
            "use_date": use_date.isoformat(),
            "start": start_time.strftime("%H:%M"),
            "end": check.end_at.strftime("%H:%M"),
            "duration_min": duration,
            "practice_type": practice_type,
            "room": room,
            "equipment": equipment,
            "members": members,
            "existing_min": int(existing),
            "opens_at": fmt(check.opens_at),
            "status": STATUS_PLANNED,
        }
    )
    save_plans(plans)
    st.success("予定として登録しました（まだ予約は完了していません）。")

st.header("3. 登録済みの予定")
plans = load_plans()
if not plans:
    st.write("まだ予定はありません。")
for p in plans:
    booked = p["status"] == STATUS_BOOKED
    if booked:
        how = "・".join(x for x in (p.get("booked_by"), p.get("booked_room")) if x)
        label = f"✅ 予約完了{f'（{how}）' if how else ''}"
    else:
        label = "📝 予定（未予約）"
    with st.container(border=True):
        st.write(f"{label}　{p['use_date']} {p['start']}〜{p['end']}　{p['room']}（{p['practice_type']}）")
        members_note = f"　同時利用者：{len(p['members'])}人" if p.get("members") else ""
        st.caption(f"予約可能：{p['opens_at']}　設備：{p['equipment'] or 'なし'}{members_note}")
        if booked:
            if st.button("削除", key=f"del{p['id']}"):
                save_plans([x for x in plans if x["id"] != p["id"]])
                st.rerun()
            continue

        total = p.get("existing_min", 0) + booked_minutes_on(plans, date.fromisoformat(p["use_date"]), p["id"])
        total += p["duration_min"]
        over = total > DAILY_LIMIT_MIN
        if over:
            st.warning(f"この日の合計が{total}分になり、{DAILY_LIMIT_MIN}分を超えるため自動予約できません。")
        col1, col2, col3 = st.columns(3)
        if col1.button("自動予約を起動", key=f"auto{p['id']}", disabled=over, type="primary"):
            launch_auto_reserve(p["id"])
            st.success("新しいウィンドウで自動予約を起動しました。予約可能日時まで、そのウィンドウを閉じずにお待ちください。")
        if col2.button("手動で予約した → 完了にする", key=f"done{p['id']}"):
            for x in plans:
                if x["id"] == p["id"]:
                    x.update(status=STATUS_BOOKED, booked_by="手動")
            save_plans(plans)
            st.rerun()
        if col3.button("削除", key=f"del{p['id']}"):
            save_plans([x for x in plans if x["id"] != p["id"]])
            st.rerun()

st.caption("自動予約が完了すると、この一覧が「予約完了（自動）」に変わります。表示が変わらないときは、ページを再読み込みしてください。")
