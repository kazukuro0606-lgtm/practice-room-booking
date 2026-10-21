"""練習室の予約予定を登録する画面（PC内だけで動く試作）。

大学サイトへのアクセス・ログイン・予約送信は一切行わない。
ここで登録するのは「予定」であり、実際の予約は大学サイトで本人が手動で行う。
"""

import json
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

DATA_FILE = Path(__file__).parent / "data" / "plans.json"

ROOMS = [ROOM_3F, ROOM_TB]
PRACTICE_TYPES = [PRACTICE_SOLO, PRACTICE_ENSEMBLE]
STATUS_PLANNED = "予定（未予約）"
STATUS_BOOKED = "予約完了（大学サイトで手動予約済み）"


def load_plans() -> list[dict]:
    if not DATA_FILE.exists():
        return []
    return json.loads(DATA_FILE.read_text(encoding="utf-8"))


def save_plans(plans: list[dict]) -> None:
    DATA_FILE.parent.mkdir(exist_ok=True)
    DATA_FILE.write_text(json.dumps(plans, ensure_ascii=False, indent=2), encoding="utf-8")


def duration_label(minutes: int) -> str:
    hours, rest = divmod(minutes, 60)
    return "".join([f"{hours}時間" if hours else "", f"{rest}分" if rest else ""])


def fmt(dt) -> str:
    return dt.strftime("%Y-%m-%d %H:%M")


st.set_page_config(page_title="練習室予約の予定", page_icon="🎵")
st.title("練習室予約の予定登録")
st.caption(
    "この画面は予定を記録するだけです。大学サイトへの接続や予約送信は行いません。"
    "自分のログインID・パスワードはここに入力しないでください。"
)

st.header("1. 予定を入力")
use_date = st.date_input("利用日", value=date.today())
start_time = st.time_input("開始時刻", value=time(15, 0), step=1800)
duration = st.radio(
    "利用時間",
    DURATION_CHOICES_MIN,
    format_func=duration_label,
    horizontal=True,
)
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
    "同じ利用日の既存予約時間（分・手入力）", min_value=0, max_value=1440, value=0, step=30
)

check = check_plan(use_date, start_time, duration, int(existing), practice_type, room)

st.header("2. 確認")
st.write(f"利用時間：{use_date:%Y-%m-%d} {start_time:%H:%M} 〜 {fmt(check.end_at)}（Asia/Tokyo）")
st.info(f"予約可能になる日時：**{fmt(check.opens_at)}**（利用終了の7日前）")
st.write(f"この日の合計：既存 {int(existing)}分 ＋ 希望 {duration}分 ＝ **{check.daily_total_min}分**")
if check.over_daily_limit:
    st.warning(f"この日の合計が{DAILY_LIMIT_MIN}分を超えています。")
if check.room_advice:
    st.warning(check.room_advice)
if check.over_room_limit:
    st.error(f"{room}は{duration_label(ROOM_MAX_MIN[room])}までしか予約できません。")
if room == ROOM_TB and not members:
    st.error("TBの部屋では、同時利用者の学籍番号が必要です。")

can_register = not check.over_room_limit and not (room == ROOM_TB and not members)
if st.button("予定として登録する", disabled=not can_register):
    plans = load_plans()
    plans.append(
        {
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
for i, p in enumerate(plans):
    booked = p["status"] == STATUS_BOOKED
    label = "✅ 予約完了" if booked else "📝 予定（未予約）"
    with st.container(border=True):
        st.write(
            f"{label}　{p['use_date']} {p['start']}〜{p['end']}　{p['room']}（{p['practice_type']}）"
        )
        members_note = f"　同時利用者：{len(p['members'])}人" if p.get("members") else ""
        st.caption(f"予約可能：{p['opens_at']}　設備：{p['equipment'] or 'なし'}{members_note}")
        col1, col2 = st.columns(2)
        if not booked and col1.button("大学サイトで予約した → 完了にする", key=f"done{i}"):
            p["status"] = STATUS_BOOKED
            save_plans(plans)
            st.rerun()
        if col2.button("削除", key=f"del{i}"):
            plans.pop(i)
            save_plans(plans)
            st.rerun()
