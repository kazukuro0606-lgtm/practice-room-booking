"""部屋の名前と予約サイトの番号（event_id）、部屋ごとの決まり。

番号は予約状況の画面の一覧（list_rooms.py、2026-10-22）から写したもの。
"""

import re

from booking_rules import PRACTICE_ENSEMBLE, PRACTICE_SOLO
from notices import NOTICE_VERSION

ROOM_IDS = {
    # 2階
    "E215": 154, "E220": 155, "E221": 156, "E222": 157, "E223": 158, "E224": 159, "E225": 160,
    "E226": 161, "E227": 162, "E228": 163, "E229": 164, "E230": 165, "E231": 166, "E232": 167,
    "E233": 168, "E234": 169, "E235": 170, "E236": 171, "E237": 172, "E238": 173, "E251": 180,
    # 3階（E312・E313 はアンサンブル用の部屋）
    "E312": 116, "E313": 117, "E320": 120, "E321": 121, "E322": 122, "E323": 233,
    "E324": 124, "E325": 125, "E326": 126, "E327": 127, "E328": 128, "E329": 129,
    "E330": 130, "E331": 131, "E332": 132, "E333": 133, "E334": 134, "E335": 135,
    "E336": 136, "E337": 137, "E338": 138, "E341": 139, "E342": 140, "E343": 141,
    "E344": 142, "E345": 143, "E346": 144, "E351": 145, "E352": 146, "E353": 147,
    "E354": 148, "E355": 149, "E356": 150,
    # 4階
    "E412": 292, "E414": 294, "E415": 295, "E420": 105, "E421": 106, "E422": 107, "E423": 108,
    "E424": 109, "E425": 110, "E426": 111, "E427": 112, "E428": 113, "E429": 114, "E430": 115,
    "E432": 95, "E441": 288, "E442": 289, "E451": 290, "E452": 291,
}

# 部屋名の後ろに付いている楽器の印
ROOM_NOTES = {"E412": "OB.FG.", "E432": "CL.", "E441": "SX.", "E442": "TP.", "E451": "HR.", "E452": "TB."}

# 予約画面の作りを確かめた部屋だけを、自動予約に使える（check_room.py で 2026-10-22 に調べた結果）
_FLOOR_3_SOLO = [r for r in ROOM_IDS if r.startswith("E3") and r not in ("E312", "E313")]
# ふつうの部屋（ラベル Small）：注意事項なし、3時間まで
PLAIN_ROOMS = (
    {r for r in ROOM_IDS if r.startswith("E2") and r != "E215"}
    | set(_FLOOR_3_SOLO)
    | {f"E4{n}" for n in range(20, 31)}
)
# 注意事項「複数人利用 優先のお願い」がある部屋（ラベル Medium／Large）：同時利用者が必須、2時間まで
NOTICE_ROOMS = {"E215", "E312", "E313", "E412", "E414", "E415", "E432", "E441", "E442", "E451", "E452"}
# さらに「担当教員名」（主科の担当教員名。該当しない場合は AA）が必須の部屋
TEACHER_ROOMS = {"E313"}
# コースの学生だけが使える部屋（大学の予約ルール「エチュードステーション練習室予約について」）。
# 予約サイトはその人のコースで使える部屋だけを見せるので、アカウントの確認（account_check.py）で
# その人に見えると分かった部屋だけを使う。確認が済むまでは使わない
WIND_ONLY_ROOMS = {"E412", "E432", "E441", "E442", "E451", "E452"}  # 管楽器コースのみ
COURSE_ROOMS = WIND_ONLY_ROOMS | {"E311"}  # E311 はピアノコースのみ（まだ番号が分からないので ROOM_IDS にない）
VERIFIED_ROOMS = PLAIN_ROOMS | NOTICE_ROOMS

# 部屋ごとの決まり
MAX_MINUTES = {r: 120 for r in NOTICE_ROOMS}  # 予約サイトで選べる利用時間の上限（書いていない部屋は3時間）
NEEDS_MEMBERS = NOTICE_ROOMS  # 注意事項の確認と同時利用者の入力が必須

# 設定していない人が使う部屋（この順に試す）
DEFAULT_ROOMS = {PRACTICE_SOLO: _FLOOR_3_SOLO, PRACTICE_ENSEMBLE: ["E452"]}

# 1回の予約で試す部屋の数の上限
MAX_ROOMS_TO_TRY = 5


def room_key(room: str) -> str:
    key = room.strip().upper().removesuffix("室")
    if key not in ROOM_IDS:
        raise ValueError(f"{room} という部屋は一覧にありません")
    return key


def event_id_of(room: str) -> int:
    return ROOM_IDS[room_key(room)]


def room_label(room: str) -> str:
    note = ROOM_NOTES.get(room)
    return f"{room}室({note})" if note else f"{room}室"


def usable_rooms(approved: bool, has_teacher: bool = False, visible: set[str] | None = None) -> list[str]:
    """自動予約に使える部屋（一覧の順）。

    注意事項のある部屋は、その人が文面を承認しているときだけ。担当教員名が必須の部屋は、さらに設定しているときだけ。
    visible（予約サイトでその人に見える部屋）が分かっているときは、その中だけ。
    コースの学生だけが使える部屋は、その人に見えると分かっているときだけ。
    """
    return [
        r
        for r in ROOM_IDS
        if (visible is None or r in visible)
        and (r not in COURSE_ROOMS or visible is not None)
        and (r in PLAIN_ROOMS or (approved and r in NOTICE_ROOMS and (has_teacher or r not in TEACHER_ROOMS)))
    ]


def permissions(settings: dict, visible: set[str] | None = None) -> dict:
    """その人の設定と見える部屋から、使える部屋を決める条件を作る（usable_rooms・rooms_for_plan に渡す）。"""
    return {
        "approved": notice_approved(settings),
        "has_teacher": bool(settings.get("teacher_name")),
        "visible": visible,
    }


def notice_approved(settings: dict) -> bool:
    """その人が、注意事項の今の文面を承認しているか。"""
    return NOTICE_VERSION in settings.get("approved_notices", [])


def max_minutes(room: str) -> int:
    return MAX_MINUTES.get(room, 180)


def rooms_setting(settings: dict, visible: set[str] | None = None) -> dict[str, list[str]]:
    """その人が設定した、練習の種類ごとの部屋（この順に試す）。設定がなければ初期値。

    部屋を選べるようになる前の設定（3階の「よく使う部屋」）は、それを先頭にした3階の部屋として引き継ぐ。
    注意事項のある部屋は、その人が文面を承認していなければ外す（空になることもある）。
    """
    allowed = set(usable_rooms(**permissions(settings, visible)))
    chosen = settings.get("rooms") or {}
    favorites = [r for r in settings.get("favorite_rooms", []) if r in DEFAULT_ROOMS[PRACTICE_SOLO]]
    legacy_solo = favorites + [r for r in DEFAULT_ROOMS[PRACTICE_SOLO] if r not in favorites]
    result = {}
    for practice, default in ((PRACTICE_SOLO, legacy_solo), (PRACTICE_ENSEMBLE, DEFAULT_ROOMS[PRACTICE_ENSEMBLE])):
        rooms = chosen.get(practice) or default
        result[practice] = [r for r in rooms if r in allowed]
    return result


def rooms_for_plan(
    chosen: list[str], minutes: int, approved: bool, has_teacher: bool = False, visible: set[str] | None = None
) -> tuple[list[str], list[str]]:
    """この予定で試す部屋（最大5室）と、利用時間が長すぎて外した部屋を返す。

    注意事項のある部屋は、その人が文面を承認していなければ外す（承認を取り消した後に動く予定のため）。
    担当教員名が必須の部屋は、担当教員名を設定していなければ外す。その人に見えない部屋も外す。
    """
    allowed = set(usable_rooms(approved, has_teacher, visible))
    usable = [r for r in chosen if r in allowed]
    too_long = [r for r in usable if minutes > max_minutes(r)]
    to_try = [r for r in usable if r not in too_long][:MAX_ROOMS_TO_TRY]
    return to_try, too_long


def needs_members(rooms: list[str]) -> bool:
    return any(r in NEEDS_MEMBERS for r in rooms)


# 部屋の選択肢「番号=E311室(…)」から、番号と部屋名（E311）を取り出す
ROOM_OPTION = re.compile(r"^(\d+)=(E\d{3})")


def compare_room_options(options: list[str]) -> list[str]:
    """部屋の選択肢を、このアプリに登録してある部屋と比べた結果の行。"""
    found = {m.group(2): int(m.group(1)) for o in options if (m := ROOM_OPTION.match(o))}
    new = [f"  {room}：番号 {event_id}" for room, event_id in found.items() if room not in ROOM_IDS]
    changed = [
        f"  {room}：アプリでは {ROOM_IDS[room]}、画面では {event_id}"
        for room, event_id in found.items()
        if room in ROOM_IDS and ROOM_IDS[room] != event_id
    ]
    missing = [r for r in ROOM_IDS if r not in found]
    lines = ["[このアプリに未登録の部屋]"] + (new or ["  なし"])
    lines += ["[番号が違う部屋]"] + (changed or ["  なし"])
    lines += ["[アプリにあるが、この画面に出ていない部屋]", "  " + (", ".join(missing) or "なし")]
    return lines
