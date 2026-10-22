"""練習室の予約予定を登録する画面（PCの localhost で動き、Tailscale Serve 経由でスマホからも開く）。

人ごとのアカウント（app_auth.py）でログインし、各自が自分の予定・設定・予約サイトのログイン情報だけを扱う。
この画面自体は大学サイトに接続しない。「予約係に任せる」を押した予定は、PCで動いている予約係（scheduler.py）が
予約可能日時に、予定を登録した本人のログイン情報で予約する。
"""

import importlib
import smtplib
import sys
import threading
import time as time_module
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, time, timedelta
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

_APP_DIR = Path(__file__).resolve().parent


@st.cache_resource
def _code_state() -> dict:
    """このプロセスで最後に読み込んだときの、このフォルダの .py の更新時刻（画面を読み込み直しても残る）。"""
    return {"newest": None, "lock": threading.Lock()}


def _reload_changed_code() -> None:
    """git pull の後、新しい app.py が古い rooms.py などを使って ImportError にならないように、
    このフォルダの .py が変わっていたら、読み込み済みの部品を読み直す（Streamlit の自動の読み直しは、
    Windows では間に合わないことがあった）。このプロセスで最初に画面を開いたときも読み直す。
    """
    state = _code_state()
    newest = max(p.stat().st_mtime for p in _APP_DIR.glob("*.py"))
    with state["lock"]:  # 同時に開いた人どうしで、読み直しの途中の部品を使わないように
        if state["newest"] == newest:
            return
        stale = [name for name, module in list(sys.modules.items())
                 if name != "__main__" and getattr(module, "__file__", None)
                 and Path(module.__file__).resolve().parent == _APP_DIR]
        for name in stale:
            del sys.modules[name]
        for name in stale:
            try:
                importlib.import_module(name)
            except ImportError:
                pass  # 更新で無くなった部品
        state["newest"] = newest


_reload_changed_code()

import account_check  # noqa: E402（上で部品を読み直してから読み込む）
import account_checks
import app_auth
import credentials
import email_verify
import mailer
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
    rename_owner,
    save_settings,
    scheduler_last_seen,
    scheduler_note,
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
    PIANO_KINDS,
    piano_of,
    room_label,
    room_label_with_piano,
    rooms_for_plan,
    rooms_setting,
    usable_rooms,
)

# この時間操作がなければログアウトする
SESSION_TIMEOUT = timedelta(minutes=30)
# 予約係はこの間隔より短く「動いている印」を書く。これより古ければ止まっているとみなす
SCHEDULER_TIMEOUT = timedelta(minutes=2)
PRACTICE_TYPES = [PRACTICE_SOLO, PRACTICE_ENSEMBLE]
# 予約サイトのログイン情報を保存する前の確認で、この時間内にこの回数ログインできなければ、しばらく試させない
# （何度も間違えると、予約サイト側でアカウントが止められるおそれがあるため）
SITE_LOGIN_WINDOW = timedelta(minutes=15)
SITE_LOGIN_MAX_FAILURES = 3
# お知らせメールの確認番号は、この時間内にこの回数まで送れる（いたずらで大量に送られないように）
EMAIL_CODE_WINDOW = timedelta(minutes=15)
EMAIL_CODE_MAX_SENDS = 3


def duration_label(minutes: int) -> str:
    hours, rest = divmod(minutes, 60)
    return "".join([f"{hours}時間" if hours else "", f"{rest}分" if rest else ""])


def fmt(dt) -> str:
    return dt.strftime("%Y-%m-%d %H:%M")


def rooms_text(rooms: list[str]) -> str:
    return "、".join(room_label_with_piano(r) for r in rooms)


def plan_rooms_text(plan: dict) -> str:
    """一覧に出す部屋。部屋を人ごとに選べるようになる前の予定は「希望する部屋」をそのまま出す。"""
    rooms = plan.get("rooms")
    if not rooms:
        return plan.get("room", "")
    return room_label(rooms[0]) if len(rooms) == 1 else f"{room_label(rooms[0])} ほか{len(rooms) - 1}室"


def scheduler_running(now: datetime) -> bool:
    last_seen = scheduler_last_seen()
    return last_seen is not None and now - last_seen < SCHEDULER_TIMEOUT


@st.cache_resource
def site_login_failures() -> dict[str, list[datetime]]:
    """人ごとの、保存前の確認でログインできなかった時刻（画面を開き直しても、ログインし直しても続く）。"""
    return {}


def verify_site_login(user: str, login_id: str, password: str, now: datetime) -> str | None:
    """予約サイトにログインできるか確かめる。保存してよければ None、だめなら理由を返す。"""
    login_id = login_id.strip()
    if not login_id or not password:
        return "ログインIDとパスワードの両方を入力してください。"
    failures = [t for t in site_login_failures().get(user, []) if now - t < SITE_LOGIN_WINDOW]
    site_login_failures()[user] = failures
    if len(failures) >= SITE_LOGIN_MAX_FAILURES:
        wait = int((failures[0] + SITE_LOGIN_WINDOW - now).total_seconds() // 60) + 1
        return (f"ログインできない入力が続いたため、確認を止めています。{wait}分ほど待ってから、"
                "ログインIDとパスワードを確かめて入れ直してください（予約サイトのアカウントが止められるのを防ぐためです）。")
    with st.spinner("予約サイトにログインできるか確かめています（20秒ほどかかることがあります）…"):
        # Playwright は、画面の処理とは別のスレッドで動かす
        with ThreadPoolExecutor(max_workers=1) as pool:
            result = pool.submit(account_check.try_login, login_id, password).result()
    if result == account_check.LOGIN_OK:
        site_login_failures().pop(user, None)
        return None
    if result == account_check.LOGIN_WRONG:
        failures.append(now)
        left = SITE_LOGIN_MAX_FAILURES - len(failures)
        return ("予約サイトにログインできませんでした。ログインIDとパスワードを確かめてください。保存していません。"
                + (f"（あと{left}回まで試せます）" if left > 0 else ""))
    return "予約サイトを開けなかったため、確かめられませんでした。保存していません。少し待ってから、もう一度保存してください。"


@st.cache_resource
def email_code_sends() -> dict[str, list[datetime]]:
    """人ごとの、確認番号のメールを送った時刻。"""
    return {}


def send_email_code(user: str, address: str, now: datetime) -> str | None:
    """お知らせメールの宛先に確認番号を送る。送れたら None、だめなら理由を返す。"""
    if problem := mailer.address_problem(address):
        return problem + "。"
    sends = [t for t in email_code_sends().get(user, []) if now - t < EMAIL_CODE_WINDOW]
    if len(sends) >= EMAIL_CODE_MAX_SENDS:
        return "確認番号を続けて送ったため、しばらく送れません。15分ほど待ってから、もう一度試してください。"
    code = email_verify.new_code()
    body = "\n".join([
        "練習室予約のアプリで、このアドレスがお知らせメールの宛先として登録されようとしています。",
        "",
        f"確認番号：{code}",
        "",
        "アプリの「お知らせメール」にこの番号を入れると、登録が完了します（30分以内）。",
        "心当たりがなければ、このメールは無視してください。",
    ])
    with st.spinner("確認番号のメールを送っています…"):
        try:
            mailer.send(address, "【練習室】お知らせメールの確認番号", body)
        except Exception as e:
            # 例外の文面にアドレスなどが含まれうるので、種類だけを出す
            return f"確認番号のメールを送れませんでした（{type(e).__name__}）。アドレスを確かめてください。"
    email_code_sends()[user] = sends + [now]
    save_settings(user, {**load_settings(user), "email_pending": email_verify.pending_for(address, code, now)})
    return None


def save_mail_sender(address: str, app_password: str) -> str | None:
    """送り元の Gmail で試しのメールを自分宛てに送り、届けば保存する。保存できたら None、だめなら理由を返す。"""
    if problem := mailer.address_problem(address):
        return problem + "。"
    app_password = mailer.normalize_app_password(app_password)
    if len(app_password) != 16:
        return "アプリパスワードは16文字です（Google が表示した4文字ずつの区切りの空白はあってもかまいません）。"
    body = "練習室予約のアプリから、お知らせメールの送り元として送れることを確かめるための、試しのメールです。"
    with st.spinner("試しのメールを送っています…"):
        try:
            mailer.send(address, "【練習室】お知らせメールの試し", body, sender_address=address, app_password=app_password)
        except smtplib.SMTPAuthenticationError:
            return ("Gmail にログインできませんでした。アドレスとアプリパスワード、"
                    "その Google アカウントの2段階認証がオンになっているかを確かめてください。")
        except Exception as e:
            return f"試しのメールを送れませんでした（{type(e).__name__}）。"
    mailer.store(address, app_password)
    return None


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
        # スマホのパスワード管理（iPhone のキーチェーンなど）が、ユーザー名とパスワードを自動で入れられるようにする
        username = st.text_input("ユーザー名", autocomplete="username")
        password = st.text_input("パスワード", type="password", autocomplete="current-password")
        if st.form_submit_button("ログイン"):
            username = username.strip().lower()
            if blocked := app_auth.login_blocked(username, now):
                st.error(blocked)
                st.stop()
            # コピーして貼り付けたときに前後に入りがちな空白・改行は除いて確かめる（パスワードに空白は使わない前提）
            if app_auth.verify(username, password) or app_auth.verify(username, password.strip()):
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


def rename_account(old: str, new: str) -> None:
    """ユーザー名を変え、その人の予定・設定・予約サイトのログイン情報・アカウントの確認結果も新しい名前に移す。"""
    app_auth.rename_user(old, new)  # 使えない名前なら、ここで止まり何も移さない
    rename_owner(old, new)
    credentials.rename(old, new)
    account_checks.rename_check(old, new)


def require_password_change(user: str) -> None:
    """パスワードを変える必要がある人には、変えるまで変更の欄だけを出す。

    管理者が作った最初のアカウント（最初のパスワードのまま）なら、ユーザー名もここで変えられる。
    """
    if not st.session_state.get("must_change"):
        return
    can_rename = app_auth.must_change_password(user)
    st.title("ユーザー名とパスワードを決めてください" if can_rename else "パスワードを変えてください")
    if can_rename:
        st.write(
            "ユーザー名は、管理者が付けたもののままでも、好きなものに変えてもかまいません"
            "（英小文字・数字・_・- の2〜20文字）。変えたら、次からは新しいユーザー名でログインします。"
        )
    st.write(
        f"使い始める前に、自分だけが知っているパスワードに変えてください。{app_auth.MIN_LENGTH}文字以上で、"
        "数字だけ・ユーザー名を含む・よく使われる言葉を含むものは使えません。予約サイトのパスワードとは別のものにしてください。"
    )
    with st.form("forced_change", clear_on_submit=True):
        name = st.text_input("ユーザー名", value=user, autocomplete="username") if can_rename else user
        new = st.text_input("新しいパスワード", type="password", autocomplete="new-password")
        again = st.text_input("もう一度", type="password", autocomplete="new-password")
        if st.form_submit_button("決定する" if can_rename else "変更する"):
            name = name.strip()
            renaming = name != user
            if new != again:
                st.error("2回の入力が一致しません。")
            elif renaming and (problem := app_auth.username_problem(name)):
                st.error(problem)
            elif problem := app_auth.password_problem(new, name):
                st.error(problem)
            else:
                if renaming:
                    rename_account(user, name)
                    st.session_state["user"] = name
                app_auth.set_password(name, new)
                st.session_state["must_change"] = False
                st.rerun()
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
just_saved = st.session_state.pop("site_login_saved", False)
with st.expander("予約サイトのログイン情報" + credentials_title,
                 expanded=just_saved or not has_credentials or check_status in (STATUS_LOGIN_FAILED, STATUS_ERROR)):
    st.caption(
        "自動予約は、あなたのログインIDとパスワードで予約サイトにログインして予約します。"
        "入力した内容は、予約係のPCの資格情報マネージャーに保存され、この画面には表示されません。"
    )
    with st.form("credentials", clear_on_submit=True):
        login_id = st.text_input("予約サイトのログインID")
        site_password = st.text_input("予約サイトのパスワード", type="password")
        if st.form_submit_button("保存する"):
            # 保存する前に、その入力で予約サイトにログインできるか確かめる
            if problem := verify_site_login(user, login_id, site_password, datetime.now(TOKYO)):
                st.error(problem)
            else:
                try:
                    credentials.store(user, login_id, site_password)
                    # 予約係が、あなたに見える部屋を確かめる
                    request_check(user)
                    st.session_state["site_login_saved"] = True
                    st.rerun()
                except ValueError as e:
                    st.error(str(e))
    if just_saved:
        st.success("予約サイトにログインできることを確かめて、保存しました。")
    if has_credentials:
        if check_status in (None, STATUS_QUEUED, STATUS_RUNNING):
            st.info("予約係が、あなたに見える部屋を確かめています（数分かかります）。再読み込みすると結果が出ます。")
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
    pianos = st.pills(
        "ピアノで絞り込む（選んだ種類の部屋だけを、下の一覧に出します）",
        PIANO_KINDS,
        selection_mode="multi",
        default=list(PIANO_KINDS),
        key="piano_filter",
    )
    chosen = {}
    for practice in PRACTICE_TYPES:
        key = f"rooms_{practice}"
        # 選んである部屋は、絞り込みで外れても一覧に残す（外すときは × で外す）
        selected = st.session_state.get(key, my_rooms[practice])
        options = [r for r in usable_rooms(**perms)
                   if piano_of(r) in pianos or piano_of(r) not in PIANO_KINDS or r in selected]
        chosen[practice] = st.multiselect(
            f"{practice}で使う部屋（選んだ順に試します）",
            options,
            default=[r for r in my_rooms[practice] if r in options],
            format_func=room_label_with_piano,
            key=key,
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

# ---- お知らせメール ----
mail_settings = load_settings(user)
my_email = mail_settings.get("email")
email_pending = mail_settings.get("email_pending")
email_flash = st.session_state.pop("email_flash", None)
with st.expander("お知らせメール" + (f"（登録済み：{my_email}）" if my_email else "（未登録・任意）"),
                 expanded=bool(email_flash or email_pending)):
    st.caption("予約係に任せた予定の結果（予約完了・予約できなかった）を、メールで知らせます。メールに書くのは日時・部屋・結果だけです。")
    if email_flash:
        st.success(email_flash)
    if not mailer.configured():
        st.info("管理者がまだメールの送り元を設定していないため、いまは登録できません。")
    else:
        with st.form("email_address", clear_on_submit=True):
            address = st.text_input("メールアドレス" if not my_email else "別のメールアドレスに変える", autocomplete="email")
            if st.form_submit_button("確認番号を送る"):
                if problem := send_email_code(user, address.strip(), datetime.now(TOKYO)):
                    st.error(problem)
                else:
                    st.session_state["email_flash"] = "確認番号を送りました。届いたメールの6桁の番号を、下に入れてください。"
                    st.rerun()
        if email_pending:
            st.write(f"**{email_pending['address']}** に送った確認番号を入れてください（30分以内）。"
                     "届かないときは、迷惑メールのフォルダも見てください。")
            with st.form("email_code", clear_on_submit=True):
                code = st.text_input("確認番号（6桁）", max_chars=6, autocomplete="one-time-code")
                if st.form_submit_button("登録する"):
                    current = load_settings(user)
                    pending = current.get("email_pending")
                    ok, why = email_verify.check(pending, code, datetime.now(TOKYO))
                    if ok:
                        save_settings(user, {**current, "email": pending["address"], "email_pending": None})
                        st.session_state["email_flash"] = f"{pending['address']} を登録しました。予約の結果をこのアドレスに知らせます。"
                        st.rerun()
                    if pending:
                        save_settings(user, {**current, "email_pending": {**pending, "tries": pending.get("tries", 0) + 1}})
                    st.error(why)
    if my_email and st.button("お知らせメールの登録を取り消す"):
        save_settings(user, {**load_settings(user), "email": "", "email_pending": None})
        st.session_state["email_flash"] = "登録を取り消しました。メールは届かなくなります。"
        st.rerun()

# ---- 管理者：アカウントの管理 ----
if admin:
    sender_now = mailer.sender()
    sender_flash = st.session_state.pop("sender_flash", None)
    with st.expander("お知らせメールの送り元（管理者だけに表示）" + (f"（設定済み：{sender_now}）" if sender_now else "（未設定）"),
                     expanded=bool(sender_flash)):
        if sender_flash:
            st.success(sender_flash)
        st.caption(
            "お知らせメールを送る Gmail のアドレスと、その Google アカウントで作った「アプリパスワード」（16文字）を入れます。"
            "保存する前に、そのアドレス宛てに試しのメールを1通送って確かめます。"
            "入力した内容は、このPCの資格情報マネージャーに保存され、画面には表示されません。"
        )
        with st.form("mail_sender", clear_on_submit=True):
            gmail = st.text_input("送り元の Gmail アドレス", autocomplete="off")
            app_password = st.text_input("アプリパスワード（16文字）", type="password", autocomplete="off")
            if st.form_submit_button("試しのメールを送って保存する"):
                if problem := save_mail_sender(gmail.strip(), app_password):
                    st.error(problem)
                else:
                    st.session_state["sender_flash"] = f"{gmail.strip()} から送れることを確かめて、保存しました。受信箱に試しのメールが届いているはずです。"
                    st.rerun()
        if sender_now and st.button("送り元の設定を削除する（お知らせメールを止める）"):
            mailer.delete()
            st.session_state["sender_flash"] = "送り元の設定を削除しました。お知らせメールは送られなくなります。"
            st.rerun()
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
                    # 枠の右上のボタンで、それぞれだけをコピーできる
                    st.caption("ユーザー名")
                    st.code(new_name.strip(), language=None)
                    st.caption("最初のパスワード")
                    st.code(first_password, language=None)
                    st.caption("本人は最初のログインで、ユーザー名を好きなものに変えられ、自分のパスワードに変えるよう求められます。")
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
                st.caption("新しいパスワード（枠の右上のボタンでコピーできます）")
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

renamed_to = st.session_state.pop("renamed_to", None)
with st.expander("この画面のユーザー名を変える", expanded=bool(renamed_to)):
    st.caption("予定・設定・予約サイトのログイン情報は、新しいユーザー名にそのまま引き継がれます。変えたら、次からは新しいユーザー名でログインします。")
    # 自動予約やアカウントの確認の途中で名前が変わると、その人のログイン情報が見つからなくなるので、終わるまで待ってもらう
    busy = any(p.get("auto") == AUTO_RUNNING for p in plans_of(load_plans(), user)) or check_status == STATUS_RUNNING
    if busy:
        st.info("いま予約係が、あなたの自動予約かアカウントの確認を実行中です。終わってから変えてください。")
    with st.form("change_username", clear_on_submit=True):
        name = st.text_input("新しいユーザー名（英小文字・数字・_・- の2〜20文字）", autocomplete="username")
        current = st.text_input("今のパスワード（確認のため）", type="password", autocomplete="current-password")
        if st.form_submit_button("変更する", disabled=busy):
            name = name.strip()
            # 貼り付けたときの前後の空白は除いて確かめる（ログインと同じ）
            password = current if app_auth.verify(user, current) else current.strip()
            if not app_auth.verify(user, password):
                st.error("今のパスワードが違います。")
            elif name == user:
                st.error("今と同じユーザー名です。")
            elif problem := app_auth.username_problem(name):
                st.error(problem)
            elif app_auth.password_problem(password, name):
                st.error("今のパスワードに新しいユーザー名が含まれるため、その名前には変えられません。先にパスワードを変えてください。")
            else:
                rename_account(user, name)
                st.session_state["user"] = name
                st.session_state["renamed_to"] = name
                st.rerun()
    if renamed_to:
        st.success(f"ユーザー名を {renamed_to} に変えました。次からはこのユーザー名でログインしてください。")

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
        help="予約係のPCにだけ保存します。一緒に使う人には、予約に使うことを伝えておいてください。"
        + ("E311 で伴奏合わせのときは、伴奏者の氏名を入れます（予約サイトの案内どおり）。" if "E311" in plan_rooms else ""),
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
if admin and (note := scheduler_note()):
    st.warning(f"予約係からのお知らせ（管理者だけに表示）：{note}")
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
