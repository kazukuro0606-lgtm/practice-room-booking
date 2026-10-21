"""練習室の予約予定を登録する画面（PCの localhost で動き、Tailscale Serve 経由でスマホからも開く）。

人ごとのアカウント（app_auth.py）でログインし、各自が自分の予定・設定・予約サイトのログイン情報だけを扱う。
この画面自体は大学サイトに接続しない。「自動予約を起動」を押したときだけ、PC上の別ウィンドウで
auto_reserve.py を起動し、予定を登録した本人のログイン情報で予約する。
"""

import subprocess
import sys
import time as time_module
from datetime import date, time
from pathlib import Path

import streamlit as st

import app_auth
import credentials
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
from plans_store import (
    STATUS_BOOKED,
    STATUS_PLANNED,
    booked_minutes_on,
    claim_legacy,
    delete_user_data,
    load_plans,
    load_settings,
    new_id,
    plans_of,
    save_plans,
    save_settings,
)
from rooms import ROOMS_3F

APP_DIR = Path(__file__).parent
MAX_LOGIN_FAILURES = 5
ROOMS = [ROOM_3F, ROOM_TB]
PRACTICE_TYPES = [PRACTICE_SOLO, PRACTICE_ENSEMBLE]


def duration_label(minutes: int) -> str:
    hours, rest = divmod(minutes, 60)
    return "".join([f"{hours}時間" if hours else "", f"{rest}分" if rest else ""])


def fmt(dt) -> str:
    return dt.strftime("%Y-%m-%d %H:%M")


def launch_auto_reserve(plan_id: str, skip_confirm: bool) -> None:
    """自動予約を新しいPowerShell（コンソール）ウィンドウで起動する。"""
    command = [sys.executable, str(APP_DIR / "auto_reserve.py"), "--plan-id", plan_id]
    if skip_confirm:
        command.append("--yes")
    subprocess.Popen(
        command,
        cwd=APP_DIR,
        creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0),
    )


def update_own_plans(user: str, change) -> None:
    """予定ファイルを読み直し、自分の予定だけを change(list) で変えて保存する（他人の予定には触れない）。"""
    plans = load_plans()
    others = [p for p in plans if p.get("owner") != user]
    mine = plans_of(plans, user)
    change(mine)
    save_plans(others + mine)


def delete_own_plan(user: str, plan_id: str) -> None:
    plans = load_plans()
    save_plans([p for p in plans if not (p["id"] == plan_id and p.get("owner") == user)])


st.set_page_config(page_title="練習室予約の予定", page_icon="🎵")


def require_login() -> str:
    """ログインするまで、ほかの表示を止める。ログインした人のユーザー名を返す。"""
    if user := st.session_state.get("user"):
        return user
    st.title("練習室予約の予定登録")
    if not app_auth.has_users():
        st.error("アカウントがまだありません。PCのPowerShellで `python app_auth.py add-admin ユーザー名` を実行してください。")
        st.stop()
    failures = st.session_state.get("login_failures", 0)
    if failures >= MAX_LOGIN_FAILURES:
        st.error("パスワードを続けて間違えたため、ロックしました。ページを開き直してください。")
        st.stop()
    with st.form("login"):
        username = st.text_input("ユーザー名")
        password = st.text_input("パスワード", type="password")
        if st.form_submit_button("ログイン"):
            username = username.strip()
            if app_auth.verify(username, password):
                st.session_state["user"] = username
                if app_auth.is_admin(username):
                    # 複数人対応の前の予定・設定・ログイン情報を、管理者のものとして引き継ぐ
                    claim_legacy(username)
                    credentials.copy_legacy_to(username)
                st.rerun()
            st.session_state["login_failures"] = failures + 1
            time_module.sleep(1)  # 総当たりを遅くする
            st.error("ユーザー名かパスワードが違います。")
    st.stop()


user = require_login()
admin = app_auth.is_admin(user)

st.title("練習室予約の予定登録")
col_who, col_logout = st.columns([3, 1])
col_who.caption(f"ログイン中：**{user}**{'（管理者）' if admin else ''}")
if col_logout.button("ログアウト"):
    st.session_state.clear()
    st.rerun()

# ---- 予約サイトのログイン情報 ----
has_credentials = credentials.has(user)
with st.expander("予約サイトのログイン情報" + ("（保存済み）" if has_credentials else "（未保存・最初に設定してください）"),
                 expanded=not has_credentials):
    st.caption(
        "自動予約は、あなたのログインIDとパスワードで予約サイトにログインして予約します。"
        "入力した内容は、予約係のPCの資格情報マネージャーに保存され、この画面には表示されません。"
    )
    with st.form("credentials", clear_on_submit=True):
        login_id = st.text_input("予約サイトのログインID")
        site_password = st.text_input("予約サイトのパスワード", type="password")
        if st.form_submit_button("保存する"):
            try:
                credentials.store(user, login_id, site_password)
                st.success("保存しました。")
                st.rerun()
            except ValueError as e:
                st.error(str(e))
    if has_credentials and st.button("保存したログイン情報を削除"):
        credentials.delete(user)
        st.rerun()

# ---- 自動予約の設定 ----
settings = load_settings(user)
with st.expander("自動予約の設定"):
    favorites = st.multiselect(
        "個人練習で先に試す3階の部屋（選んだ順に試します）",
        list(ROOMS_3F),
        default=[r for r in settings["favorite_rooms"] if r in ROOMS_3F],
        help="選ばなかった部屋は番号順に続けて試します。1回の予約で試すのは最大5室です。",
    )
    if admin:
        skip_confirm = st.checkbox(
            "確認なしで予約する（全自動）",
            value=settings["skip_confirm"],
            help="オフのときは、「登録」を押す前に、PCに開く自動予約のウィンドウで y の入力を求めます。",
        )
        if skip_confirm:
            st.warning("全自動では、確認画面の内容を見ずに予約を送信します。")
    else:
        # 友達はPCのウィンドウで y を入力できないため、常に全自動
        skip_confirm = True
        st.caption("自動予約は、確認なし（全自動）で予約を送信します。登録する予定の内容をよく確認してください。")
    if st.button("設定を保存"):
        save_settings(user, {"favorite_rooms": favorites, "skip_confirm": skip_confirm})
        settings = load_settings(user)
        st.success("保存しました。これから起動する自動予約に反映されます。")
skip_confirm_now = settings["skip_confirm"] if admin else True

# ---- 管理者：アカウントの管理 ----
if admin:
    with st.expander("アカウントの管理（管理者だけに表示）"):
        with st.form("add_user", clear_on_submit=True):
            st.write("アカウントを作る")
            new_name = st.text_input("ユーザー名（英小文字・数字・_・- の2〜20文字）")
            new_password = st.text_input("最初のパスワード（8文字以上）", type="password")
            if st.form_submit_button("作る"):
                try:
                    app_auth.add_user(new_name.strip(), new_password)
                    st.success(f"{new_name} を作りました。ユーザー名と最初のパスワードを本人に伝えてください。")
                except ValueError as e:
                    st.error(str(e))
        others = [u for u in app_auth.list_users() if u != user]
        if others:
            target = st.selectbox("アカウントを選ぶ", others)
            with st.form("reset_password", clear_on_submit=True):
                reset_to = st.text_input(f"{target} の新しいパスワード（8文字以上）", type="password")
                if st.form_submit_button("パスワードを設定し直す"):
                    try:
                        app_auth.set_password(target, reset_to)
                        st.success(f"{target} のパスワードを設定し直しました。")
                    except ValueError as e:
                        st.error(str(e))
            confirm = st.checkbox(f"{target} の予定・設定・予約サイトのログイン情報もすべて削除することを確認しました")
            if st.button(f"{target} のアカウントを削除", disabled=not confirm):
                delete_user_data(target)
                credentials.delete(target)
                app_auth.delete_user(target)
                st.success(f"{target} を削除しました。")
                st.rerun()

# ---- 自分のパスワードの変更 ----
with st.expander("この画面のパスワードを変える"):
    with st.form("change_password", clear_on_submit=True):
        current = st.text_input("今のパスワード", type="password")
        new = st.text_input("新しいパスワード（8文字以上）", type="password")
        if st.form_submit_button("変更する"):
            if not app_auth.verify(user, current):
                st.error("今のパスワードが違います。")
            else:
                try:
                    app_auth.set_password(user, new)
                    st.success("変更しました。")
                except ValueError as e:
                    st.error(str(e))

# ---- 1. 予定を入力 ----
st.header("1. 予定を入力")
use_date = st.date_input("利用日", value=date.today())
# 時刻の入力欄は環境によって操作しにくいため、30分刻みの一覧から選ぶ
START_TIMES = [time(h, m) for h in range(24) for m in (0, 30)]
start_time = st.selectbox(
    "開始時刻", START_TIMES, index=START_TIMES.index(time(15, 0)), format_func=lambda t: t.strftime("%H:%M")
)
duration = st.radio("利用時間", DURATION_CHOICES_MIN, format_func=duration_label, horizontal=True)
practice_type = st.radio("練習の種類", PRACTICE_TYPES, horizontal=True)
room = st.selectbox("希望する部屋", ROOMS)
members_text = ""
if room == ROOM_TB:
    members_text = st.text_area(
        "同時利用者の学籍番号（1行に1人・TBの部屋では必須）",
        help="予約係のPCにだけ保存します。一緒に使う人には、予約に使うことを伝えておいてください。",
    )
members = [m.strip() for m in members_text.splitlines() if m.strip()]
equipment = st.text_input("設備条件（任意）", placeholder="例：ピアノあり、譜面台2台")
existing = st.number_input(
    "このアプリの外で取った、同じ利用日の予約時間（分）",
    min_value=0,
    max_value=1440,
    value=0,
    step=30,
    help="このアプリで「予約完了」になっているあなたの予定の時間は、自動で合計に入ります。",
)

my_plans = plans_of(load_plans(), user)
booked_in_app = booked_minutes_on(my_plans, use_date)
check = check_plan(use_date, start_time, duration, int(existing) + booked_in_app, practice_type, room)

# ---- 2. 確認 ----
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
    new_plan = {
        "id": new_id(),
        "owner": user,
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
    update_own_plans(user, lambda mine: mine.append(new_plan))
    st.success("予定として登録しました（まだ予約は完了していません）。")

# ---- 3. 登録済みの予定（自分の分だけ） ----
st.header("3. 登録済みの予定")
my_plans = plans_of(load_plans(), user)
if not my_plans:
    st.write("まだ予定はありません。")
if not has_credentials:
    st.warning("予約サイトのログイン情報が未保存なので、自動予約は起動できません。")
for p in my_plans:
    pid = p["id"]
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
        if last := p.get("last_run"):
            full = f"　埋まっていた部屋：{', '.join(last['full_rooms'])}" if last["full_rooms"] else ""
            st.caption(f"前回の自動予約（{last['at']}）：{last['result']}{full}")
        if booked:
            if st.button("削除", key=f"del{pid}"):
                delete_own_plan(user, pid)
                st.rerun()
            continue

        total = p.get("existing_min", 0) + booked_minutes_on(my_plans, date.fromisoformat(p["use_date"]), pid)
        total += p["duration_min"]
        over = total > DAILY_LIMIT_MIN
        if over:
            st.warning(f"この日の合計が{total}分になり、{DAILY_LIMIT_MIN}分を超えるため自動予約できません。")
        col1, col2, col3 = st.columns(3)
        if col1.button("自動予約を起動", key=f"auto{pid}", disabled=over or not has_credentials, type="primary"):
            launch_auto_reserve(pid, skip_confirm_now)
            mode = "全自動" if skip_confirm_now else "送信前に確認あり"
            st.success(f"予約係のPCで自動予約を起動しました（{mode}）。予約可能日時になると予約します。")
        if col2.button("手動で予約した → 完了にする", key=f"done{pid}"):
            def mark_done(mine, pid=pid):
                for x in mine:
                    if x["id"] == pid:
                        x.update(status=STATUS_BOOKED, booked_by="手動")
            update_own_plans(user, mark_done)
            st.rerun()
        if col3.button("削除", key=f"del{pid}"):
            delete_own_plan(user, pid)
            st.rerun()

st.caption("自動予約が完了すると、この一覧が「予約完了（自動）」に変わります。表示が変わらないときは、ページを再読み込みしてください。")
