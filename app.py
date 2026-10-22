"""練習室の予約予定を登録する画面（PCの localhost で動き、Tailscale Serve 経由でスマホからも開く）。

人ごとのアカウント（app_auth.py）でログインし、各自が自分の予定・設定・予約サイトのログイン情報だけを扱う。
この画面自体は大学サイトに接続しない。「予約係に任せる」を押した予定は、PCで動いている予約係（scheduler.py）が
予約可能日時に、予定を登録した本人のログイン情報で予約する。
"""

import time as time_module
from datetime import date, datetime, time, timedelta

import streamlit as st
import streamlit.components.v1 as components

import account_checks
import app_auth
import credentials
from account_checks import (
    STATUS_ERROR,
    STATUS_LOGIN_FAILED,
    STATUS_OK,
    STATUS_QUEUED,
    STATUS_RUNNING,
    load_check,
    request_check,
    visible_rooms,
)
from booking_rules import (
    CLOSE_TIME,
    DAILY_LIMIT_MIN,
    DURATION_CHOICES_MIN,
    MAX_BOOKINGS_PER_DAY,
    OPEN_TIME,
    PRACTICE_ENSEMBLE,
    PRACTICE_SOLO,
    TOKYO,
    check_plan,
    has_short_gap,
    within_hours,
)
from plans_store import (
    AUTO_OFF,
    AUTO_QUEUED,
    AUTO_RUNNING,
    STATUS_BOOKED,
    STATUS_PLANNED,
    booked_count_on,
    booked_minutes_on,
    claim_legacy,
    delete_user_data,
    load_plans,
    load_settings,
    new_id,
    plans_of,
    save_settings,
    scheduler_last_seen,
    set_auto,
    update_plans,
)
from notices import NOTICE_DISPLAY, NOTICE_VERSION
from onboarding import AGREEMENT, ONBOARDING_VERSION, PAGES
from rooms import (
    MAX_ROOMS_TO_TRY,
    NOTICE_ROOMS,
    ROOM_IDS,
    max_minutes,
    needs_members,
    notice_approved,
    permissions,
    room_label,
    rooms_for_plan,
    rooms_setting,
    usable_rooms,
)

# この時間操作がなければログアウトする
SESSION_TIMEOUT = timedelta(minutes=30)
# 予約係はこの間隔より短く「動いている印」を書く。これより古ければ止まっているとみなす
SCHEDULER_TIMEOUT = timedelta(minutes=2)
PRACTICE_TYPES = [PRACTICE_SOLO, PRACTICE_ENSEMBLE]


def duration_label(minutes: int) -> str:
    hours, rest = divmod(minutes, 60)
    return "".join([f"{hours}時間" if hours else "", f"{rest}分" if rest else ""])


def fmt(dt) -> str:
    return dt.strftime("%Y-%m-%d %H:%M")


def rooms_text(rooms: list[str]) -> str:
    return "、".join(room_label(r) for r in rooms)


def plan_rooms_text(plan: dict) -> str:
    """一覧に出す部屋。部屋を人ごとに選べるようになる前の予定は「希望する部屋」をそのまま出す。"""
    rooms = plan.get("rooms")
    if not rooms:
        return plan.get("room", "")
    return room_label(rooms[0]) if len(rooms) == 1 else f"{room_label(rooms[0])} ほか{len(rooms) - 1}室"


def scheduler_running(now: datetime) -> bool:
    last_seen = scheduler_last_seen()
    return last_seen is not None and now - last_seen < SCHEDULER_TIMEOUT


def update_own_plans(user: str, change) -> None:
    """予定ファイルを読み直し、自分の予定だけを change(list) で変えて保存する（他人の予定には触れない）。"""

    def change_mine(plans):
        others = [p for p in plans if p.get("owner") != user]
        mine = plans_of(plans, user)
        change(mine)
        return others + mine

    update_plans(change_mine)


def delete_own_plan(user: str, plan_id: str) -> None:
    update_plans(lambda plans: [p for p in plans if not (p["id"] == plan_id and p.get("owner") == user)])


st.set_page_config(page_title="練習室予約の予定", page_icon="🎵")

# Streamlit のページは「英語」を名乗るので、スマホのブラウザが自動翻訳しようとする。翻訳や、iPhone の
# データ検出（日付や番号を自動でリンクにする）で画面の文字が書き換わると、画面の更新で
# 「NotFoundError：オブジェクトが見つかりません」になるため、「日本語のページで、翻訳もリンク化もしない」と伝える
# （決まった文字だけを書き込む。入力された文字は使わない）
NO_TRANSLATE_JS = """
<script>
const doc = window.parent.document;
doc.documentElement.setAttribute("lang", "ja");
doc.documentElement.setAttribute("translate", "no");
doc.documentElement.classList.add("notranslate");
function addMeta(name, content) {
  if (doc.querySelector(`meta[name="${name}"]`)) return;
  const meta = doc.createElement("meta");
  meta.name = name;
  meta.content = content;
  doc.head.appendChild(meta);
}
addMeta("google", "notranslate");
// iPhone のブラウザが日付・時刻・番号を電話番号などと見なしてリンクに書き換えると、同じエラーになるので止める
addMeta("format-detection", "telephone=no, date=no, address=no, email=no");
</script>
"""
components.html(NO_TRANSLATE_JS, height=0)


def require_login() -> str:
    """ログインするまで、ほかの表示を止める。ログインした人のユーザー名を返す。

    一定時間操作がなければログアウトする。ログインの失敗の制限は app_auth が記録し、ページを開き直しても続く。
    """
    now = datetime.now(TOKYO)
    if user := st.session_state.get("user"):
        if now - st.session_state.get("last_active", now) > SESSION_TIMEOUT:
            st.session_state.clear()
            st.session_state["timed_out"] = True
            st.rerun()
        st.session_state["last_active"] = now
        return user
    st.title("練習室予約の予定登録")
    if st.session_state.pop("timed_out", False):
        st.info(f"{int(SESSION_TIMEOUT.total_seconds() // 60)}分間操作がなかったため、ログアウトしました。")
    if not app_auth.has_users():
        st.error("アカウントがまだありません。PCのPowerShellで `python app_auth.py add-admin ユーザー名` を実行してください。")
        st.stop()
    with st.form("login"):
        username = st.text_input("ユーザー名")
        password = st.text_input("パスワード", type="password")
        if st.form_submit_button("ログイン"):
            username = username.strip()
            if blocked := app_auth.login_blocked(username, now):
                st.error(blocked)
                st.stop()
            if app_auth.verify(username, password):
                app_auth.clear_failures(username)
                st.session_state["user"] = username
                st.session_state["last_active"] = now
                # 管理者が決めたパスワードのまま、または今の基準より弱いパスワードなら、変えるまで使わせない
                st.session_state["must_change"] = app_auth.must_change_password(username) or bool(
                    app_auth.password_problem(password, username)
                )
                if app_auth.is_admin(username):
                    # 複数人対応の前の予定・設定・ログイン情報を、管理者のものとして引き継ぐ
                    claim_legacy(username)
                    credentials.copy_legacy_to(username)
                st.rerun()
            app_auth.record_failure(username, now)
            time_module.sleep(1)  # 総当たりを遅くする
            st.error("ユーザー名かパスワードが違います。")
    st.stop()


def require_password_change(user: str) -> None:
    """パスワードを変える必要がある人には、変えるまで変更の欄だけを出す。"""
    if not st.session_state.get("must_change"):
        return
    st.title("パスワードを変えてください")
    st.write(
        f"使い始める前に、自分だけが知っているパスワードに変えてください。{app_auth.MIN_LENGTH}文字以上で、"
        "数字だけ・ユーザー名を含む・よく使われる言葉を含むものは使えません。予約サイトのパスワードとは別のものにしてください。"
    )
    with st.form("forced_change", clear_on_submit=True):
        new = st.text_input("新しいパスワード", type="password")
        again = st.text_input("もう一度", type="password")
        if st.form_submit_button("変更する"):
            if new != again:
                st.error("2回の入力が一致しません。")
            else:
                try:
                    app_auth.set_password(user, new)
                    st.session_state["must_change"] = False
                    st.rerun()
                except ValueError as e:
                    st.error(str(e))
    if st.button("ログアウト"):
        st.session_state.clear()
        st.rerun()
    st.stop()


def require_onboarding(user: str) -> None:
    """初めて使う人（と「使い方を見る」を押した人）に、注意事項と使い方を1ページずつ見せる。

    初めての人は、最後のページで同意するまでメインの画面に進めない。
    """
    settings = load_settings(user)
    first_time = settings.get("onboarded_version", 0) < ONBOARDING_VERSION
    if not first_time and not st.session_state.get("show_guide"):
        return
    page = min(st.session_state.get("guide_page", 0), len(PAGES) - 1)
    title, body = PAGES[page]
    st.title("はじめに" if first_time else "使い方")
    st.progress((page + 1) / len(PAGES), text=f"{page + 1} / {len(PAGES)}　{title}")
    st.subheader(title)
    st.markdown(body)
    last = page == len(PAGES) - 1
    if last and first_time:
        agreed = st.checkbox(AGREEMENT)
    col_back, col_next = st.columns(2)
    if page > 0 and col_back.button("← 戻る", width="stretch"):
        st.session_state["guide_page"] = page - 1
        st.rerun()
    if not last:
        if col_next.button("次へ →", type="primary", width="stretch"):
            st.session_state["guide_page"] = page + 1
            st.rerun()
    elif first_time:
        if col_next.button("使い始める", type="primary", disabled=not agreed, width="stretch"):
            # 読んでいる間に別の画面で変えた設定を消さないように、読み直してから書く
            save_settings(user, {**load_settings(user), "onboarded_version": ONBOARDING_VERSION})
            st.session_state.pop("guide_page", None)
            st.rerun()
    elif col_next.button("閉じる", type="primary", width="stretch"):
        st.session_state.pop("show_guide", None)
        st.session_state.pop("guide_page", None)
        st.rerun()
    if not first_time and page < len(PAGES) - 1 and st.button("説明を閉じる"):
        st.session_state.pop("show_guide", None)
        st.session_state.pop("guide_page", None)
        st.rerun()
    if first_time and st.button("ログアウト"):
        st.session_state.clear()
        st.rerun()
    st.stop()


user = require_login()
require_password_change(user)
require_onboarding(user)
admin = app_auth.is_admin(user)

st.title("練習室予約の予定登録")
col_who, col_guide, col_logout = st.columns([2, 1, 1])
col_who.caption(f"ログイン中：**{user}**{'（管理者）' if admin else ''}")
if col_guide.button("使い方を見る"):
    st.session_state["show_guide"] = True
    st.session_state["guide_page"] = 0
    st.rerun()
if col_logout.button("ログアウト"):
    st.session_state.clear()
    st.rerun()

# ---- 予約サイトのログイン情報 ----
has_credentials = credentials.has(user)
check = load_check(user)
check_status = check.get("status") if check else None
if not has_credentials:
    credentials_title = "（未保存・最初に設定してください）"
elif check_status == STATUS_OK:
    credentials_title = f"（確認済み：使える部屋 {len(check.get('visible_rooms', {}))}室）"
elif check_status == STATUS_LOGIN_FAILED:
    credentials_title = "（ログインできませんでした・保存し直してください）"
elif check_status == STATUS_ERROR:
    credentials_title = "（確かめられませんでした）"
else:
    credentials_title = "（予約係が確かめています）"
with st.expander("予約サイトのログイン情報" + credentials_title,
                 expanded=not has_credentials or check_status in (STATUS_LOGIN_FAILED, STATUS_ERROR)):
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
                # 予約係が、ログインできるか・あなたに見える部屋を確かめる
                request_check(user)
                st.rerun()
            except ValueError as e:
                st.error(str(e))
    if has_credentials:
        if check_status in (None, STATUS_QUEUED, STATUS_RUNNING):
            st.info("予約係が、このログイン情報でログインできるか・あなたに見える部屋を確かめています（数分かかります）。再読み込みすると結果が出ます。")
        elif check_status == STATUS_OK:
            st.success(f"ログインできました（{check['checked_at']}）。予約サイトであなたに見える部屋：{len(check.get('visible_rooms', {}))}室。")
        else:
            st.error(f"{check.get('message', '')}（{check.get('checked_at', '')}）")
        col_recheck, col_delete = st.columns(2)
        if col_recheck.button("もう一度確かめる", disabled=check_status in (STATUS_QUEUED, STATUS_RUNNING)):
            request_check(user)
            st.rerun()
        if col_delete.button("保存したログイン情報を削除"):
            credentials.delete(user)
            account_checks.delete_check(user)
            st.rerun()

# ---- 注意事項の承認 ----
settings = load_settings(user)
approved = notice_approved(settings)
with st.expander("注意事項の承認（" + ("承認済み" if approved else "未承認：承認すると使える部屋が増えます") + "）"):
    notice_rooms = [r for r in ROOM_IDS if r in NOTICE_ROOMS]
    st.caption(f"次の部屋は、予約するときに下の注意事項の確認が必須です：{rooms_text(notice_rooms)}")
    st.text(NOTICE_DISPLAY)
    st.caption(
        "承認すると、予約係があなたの予約でこれらの部屋を予約するときに、確認の欄に自動でチェックを入れます。"
        "予約サイトの文面がこれと違っていたら、同意せずに止まります。これらの部屋では、同時利用者の学籍番号が必須で、利用は2時間までです。"
    )
    if approved:
        if st.button("承認を取り消す"):
            save_settings(user, {**settings, "approved_notices": [v for v in settings["approved_notices"] if v != NOTICE_VERSION]})
            st.rerun()
    else:
        agree = st.checkbox("上の注意事項を読み、私の予約でこの確認の欄に自動でチェックを入れることを承認します")
        if st.button("承認する", disabled=not agree):
            save_settings(user, {**settings, "approved_notices": settings["approved_notices"] + [NOTICE_VERSION]})
            st.rerun()

# ---- 自動予約の設定 ----
my_visible = visible_rooms(user)
my_rooms = rooms_setting(settings, my_visible)
perms = permissions(settings, my_visible)
with st.expander("自動予約の設定（使う部屋）", expanded=bool(st.session_state.get("settings_saved"))):
    st.caption(
        f"練習の種類ごとに、使う部屋を**試したい順に**選んでください。1回の予約で、上から最大{MAX_ROOMS_TO_TRY}室を試します。"
        "選べるのは、予約画面の作りを確かめた部屋のうち、予約サイトであなたに見える部屋だけです。注意事項のある部屋（Medium・Large）は、上で承認すると選べます。"
    )
    if my_visible is None:
        st.caption("予約係があなたのアカウントを確かめるまでは、コース専用の部屋（管楽器の部屋など）は選べません。")
    chosen = {}
    for practice in PRACTICE_TYPES:
        chosen[practice] = st.multiselect(
            f"{practice}で使う部屋（選んだ順に試します）",
            usable_rooms(**perms),
            default=my_rooms[practice],
            format_func=room_label,
            key=f"rooms_{practice}",
        )
    teacher_name = st.text_input(
        "担当教員名（E313 の予約で必須。主科の担当教員名、該当しない場合は AA）",
        value=settings.get("teacher_name", ""),
        help="設定すると、注意事項を承認している人は E313 も選べるようになります（保存してから選んでください）。",
    )
    # 予約係は人がいなくても動く前提なので、確認なし（全自動）で予約を送信する
    st.caption("予約係は、確認画面で止まらずに予約を送信します（全自動）。登録する予定の内容をよく確認してください。")
    if st.button("設定を保存"):
        save_settings(user, {**settings, "rooms": chosen, "teacher_name": teacher_name.strip()})
        # 選べる部屋が変わることがあるので、画面を読み直してから知らせる
        st.session_state["settings_saved"] = True
        st.rerun()
    if st.session_state.pop("settings_saved", False):
        st.success("保存しました。これから登録する予定に使われます（登録済みの予定の部屋は変わりません）。")
    for practice, rooms in chosen.items():
        if not rooms:
            st.caption(f"{practice}の部屋が選ばれていません。{practice}の予定は登録できません。")

# ---- 管理者：アカウントの管理 ----
if admin:
    with st.expander("予約サイトのアカウントの確認結果（管理者だけに表示）"):
        for name in app_auth.list_users():
            c = load_check(name)
            if not c:
                state = "確認待ち" if credentials.has(name) else "予約サイトのログイン情報が未保存"
                st.write(f"**{name}**：{state}")
                continue
            status_text = {
                STATUS_OK: f"確認済み（見える部屋 {len(c.get('visible_rooms', {}))}室）",
                STATUS_LOGIN_FAILED: "ログインできなかった",
                STATUS_ERROR: "確かめられなかった",
            }.get(c.get("status"), "確認待ち・確認中")
            st.write(f"**{name}**：{status_text}　{c.get('checked_at', '')}　{c.get('message', '')}")
            for room, info in c.get("unknown_rooms", {}).items():
                st.caption(f"{name} に見える、アプリに未登録の部屋：{room}（番号 {info['event_id']}）")
                st.code("\n".join(info["report"]), language=None)
        st.caption("未登録の部屋は、この調査結果を Claude に送ると、注意事項や必須の欄に合わせて使えるように登録します。")

    with st.expander("アカウントの管理（管理者だけに表示）"):
        with st.form("add_user", clear_on_submit=True):
            st.write("アカウントを作る")
            new_name = st.text_input("ユーザー名（英小文字・数字・_・- の2〜20文字）")
            if st.form_submit_button("作る"):
                first_password = app_auth.generate_password()
                try:
                    app_auth.add_user(new_name.strip(), first_password, must_change=True)
                    st.success(f"{new_name} を作りました。次のユーザー名と最初のパスワードを、本人だけに伝えてください（この表示は一度だけです）。")
                    st.code(f"ユーザー名：{new_name.strip()}\n最初のパスワード：{first_password}", language=None)
                    st.caption("本人は最初のログインで、自分のパスワードに変えるよう求められます。")
                except ValueError as e:
                    st.error(str(e))
        others = [u for u in app_auth.list_users() if u != user]
        if others:
            target = st.selectbox("アカウントを選ぶ", others)
            if st.button(f"{target} のパスワードを設定し直す"):
                reset_to = app_auth.generate_password()
                app_auth.set_password(target, reset_to, must_change=True)
                app_auth.clear_failures(target)
                st.success(f"{target} のパスワードを設定し直しました。次のパスワードを本人だけに伝えてください（この表示は一度だけです）。")
                st.code(reset_to, language=None)
                st.caption("本人は次のログインで、自分のパスワードに変えるよう求められます。ロックも解除しました。")
            confirm = st.checkbox(f"{target} の予定・設定・予約サイトのログイン情報もすべて削除することを確認しました")
            if st.button(f"{target} のアカウントを削除", disabled=not confirm):
                delete_user_data(target)
                credentials.delete(target)
                account_checks.delete_check(target)
                app_auth.delete_user(target)
                st.success(f"{target} を削除しました。")
                st.rerun()

# ---- 自分のパスワードの変更 ----
with st.expander("この画面のパスワードを変える"):
    with st.form("change_password", clear_on_submit=True):
        current = st.text_input("今のパスワード", type="password")
        new = st.text_input(f"新しいパスワード（{app_auth.MIN_LENGTH}文字以上）", type="password")
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
# 大学の予約ルールで、利用できるのは 7時〜22時
START_TIMES = [time(h, m) for h in range(OPEN_TIME.hour, CLOSE_TIME.hour) for m in (0, 30)]
start_time = st.selectbox(
    "開始時刻", START_TIMES, index=START_TIMES.index(time(15, 0)), format_func=lambda t: t.strftime("%H:%M")
)
duration = st.radio("利用時間", DURATION_CHOICES_MIN, format_func=duration_label, horizontal=True)
practice_type = st.radio("練習の種類", PRACTICE_TYPES, horizontal=True)
plan_rooms, too_long = rooms_for_plan(my_rooms[practice_type], duration, **perms)
members_text = ""
if needs_members(plan_rooms):
    members_text = st.text_area(
        "同時利用者の学籍番号（1行に1人・" + rooms_text([r for r in plan_rooms if needs_members([r])]) + "では必須）",
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
check = check_plan(use_date, start_time, duration, int(existing) + booked_in_app)

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
outside_hours = not within_hours(start_time, duration)
if outside_hours:
    st.error(f"利用できるのは {OPEN_TIME:%H:%M}〜{CLOSE_TIME:%H:%M} です。終わりが {CLOSE_TIME:%H:%M} を過ぎないようにしてください。")
count_today = booked_count_on(my_plans, use_date) + 1
if count_today > MAX_BOOKINGS_PER_DAY:
    st.warning(f"この日の予約が{count_today}回目になります。1日{MAX_BOOKINGS_PER_DAY}回までなので、この予定は自動予約できません。")
same_day = [
    (time.fromisoformat(x["start"]), time.fromisoformat(x["end"])) for x in my_plans if x["use_date"] == use_date.isoformat()
]
if has_short_gap(same_day, start_time, check.end_at.time()):
    st.warning(
        "同じ日のほかの予定との間が30分以下しか空いていません。30分おきに予約と空きを作る使い方は、"
        "規程より長く使う悪質な利用とみなされることがあります。続けて使うなら、1つの予定にまとめてください。"
    )
st.caption("閉館日・短縮開館日も、予約サイトでは予約できてしまいます。開館時間を確かめてから登録してください。")
if plan_rooms:
    st.write(f"試す部屋（この順）：{rooms_text(plan_rooms)}")
if too_long:
    st.caption("利用時間が長いため試さない部屋：" + "、".join(f"{room_label(r)}（{duration_label(max_minutes(r))}まで）" for r in too_long))
if not plan_rooms:
    st.error("この利用時間で予約できる部屋がありません。利用時間を短くするか、「自動予約の設定」で部屋を見直してください。")
missing_members = needs_members(plan_rooms) and not members
if missing_members:
    st.error("同時利用者の学籍番号が必要な部屋が含まれています。")

can_register = bool(plan_rooms) and not missing_members and not outside_hours
if st.button("予定として登録する", disabled=not can_register):
    new_plan = {
        "id": new_id(),
        "owner": user,
        "use_date": use_date.isoformat(),
        "start": start_time.strftime("%H:%M"),
        "end": check.end_at.strftime("%H:%M"),
        "duration_min": duration,
        "practice_type": practice_type,
        "rooms": plan_rooms,
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
    st.warning("予約サイトのログイン情報が未保存なので、予約係に任せられません。")
if not scheduler_running(datetime.now(TOKYO)):
    st.error("予約係が動いていません。任せた予定も、予約係が動くまで予約されません。予約係のPCで `python scheduler.py` を起動してください。")
for p in my_plans:
    pid = p["id"]
    booked = p["status"] == STATUS_BOOKED
    if booked:
        how = "・".join(x for x in (p.get("booked_by"), p.get("booked_room")) if x)
        label = f"✅ 予約完了{f'（{how}）' if how else ''}"
    else:
        label = "📝 予定（未予約）"
    with st.container(border=True):
        st.write(f"{label}　{p['use_date']} {p['start']}〜{p['end']}　{plan_rooms_text(p)}（{p['practice_type']}）")
        members_note = f"　同時利用者：{len(p['members'])}人" if p.get("members") else ""
        st.caption(f"予約可能：{p['opens_at']}　設備：{p['equipment'] or 'なし'}{members_note}")
        if p.get("rooms") and not booked:
            st.caption(f"試す部屋（この順）：{rooms_text(p['rooms'])}")
        if last := p.get("last_run"):
            full = f"　埋まっていた部屋：{', '.join(last['full_rooms'])}" if last["full_rooms"] else ""
            st.caption(f"前回の自動予約（{last['at']}）：{last['result']}{full}")
        if booked:
            if st.button("削除", key=f"del{pid}"):
                delete_own_plan(user, pid)
                st.rerun()
            continue

        auto = p.get("auto", AUTO_OFF)
        if auto is AUTO_QUEUED:
            st.info("⏳ 予約係に任せています。予約可能日時の10分前に始め、時刻になったら予約します。")
        elif auto == AUTO_RUNNING:
            st.info("🔄 予約係が自動予約を実行中です。")
        total = p.get("existing_min", 0) + booked_minutes_on(my_plans, date.fromisoformat(p["use_date"]), pid)
        total += p["duration_min"]
        over = total > DAILY_LIMIT_MIN
        if over:
            st.warning(f"この日の合計が{total}分になり、{DAILY_LIMIT_MIN}分を超えるため予約係に任せられません。")
        count = booked_count_on(my_plans, date.fromisoformat(p["use_date"]), pid) + 1
        if count > MAX_BOOKINGS_PER_DAY:
            over = True
            st.warning(f"この日の予約が{count}回目になり、1日{MAX_BOOKINGS_PER_DAY}回までを超えるため予約係に任せられません。")
        col1, col2, col3 = st.columns(3)
        if auto is AUTO_OFF:
            if col1.button("予約係に任せる", key=f"auto{pid}", disabled=over or not has_credentials, type="primary"):
                set_auto(pid, AUTO_QUEUED, owner=user)
                st.rerun()
        elif col1.button("任せるのをやめる", key=f"stop{pid}"):
            # 実行中でも、予約を送る直前に取り消しを確かめて止まる
            set_auto(pid, AUTO_OFF, owner=user)
            st.rerun()
        if col2.button("手動で予約した → 完了にする", key=f"done{pid}"):
            def mark_done(mine, pid=pid):
                for x in mine:
                    if x["id"] == pid:
                        x.update(status=STATUS_BOOKED, booked_by="手動", auto=AUTO_OFF)
            update_own_plans(user, mark_done)
            st.rerun()
        # 任せている間は、予約係が予約完了を書き込む先がなくならないよう、削除できない
        if col3.button("削除", key=f"del{pid}", disabled=auto is not AUTO_OFF):
            delete_own_plan(user, pid)
            st.rerun()

st.caption("予約係が予約を完了すると、この一覧が「予約完了（自動）」に変わります。表示が変わらないときは、ページを再読み込みしてください。")
