"""部屋の名前と予約サイトの番号（event_id）、部屋ごとの決まり。

番号は予約状況の画面の一覧（list_rooms.py、2026-10-22）から写したもの。
"""

from booking_rules import PRACTICE_ENSEMBLE, PRACTICE_SOLO

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

# 予約画面の作りを確かめた部屋だけを、自動予約に使える
# （2階：E224 で練習モードを確認、3階：本番で予約済み、E452：注意事項と同時利用者に対応して本番で予約済み）
_FLOOR_2 = [r for r in ROOM_IDS if r.startswith("E2")]
_FLOOR_3_SOLO = [r for r in ROOM_IDS if r.startswith("E3") and r not in ("E312", "E313")]
VERIFIED_ROOMS = set(_FLOOR_2) | set(_FLOOR_3_SOLO) | {"E452"}

# 部屋ごとの決まり
MAX_MINUTES = {"E452": 120}  # 予約サイトで選べる利用時間の上限（書いていない部屋は3時間）
NEEDS_MEMBERS = {"E452"}  # 注意事項の確認と同時利用者の入力が必須

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


def usable_rooms() -> list[str]:
    """自動予約に使える部屋（一覧の順）。"""
    return [r for r in ROOM_IDS if r in VERIFIED_ROOMS]


def max_minutes(room: str) -> int:
    return MAX_MINUTES.get(room, 180)


def rooms_setting(settings: dict) -> dict[str, list[str]]:
    """その人が設定した、練習の種類ごとの部屋（この順に試す）。設定がなければ初期値。

    部屋を選べるようになる前の設定（3階の「よく使う部屋」）は、それを先頭にした3階の部屋として引き継ぐ。
    """
    chosen = settings.get("rooms") or {}
    favorites = [r for r in settings.get("favorite_rooms", []) if r in DEFAULT_ROOMS[PRACTICE_SOLO]]
    legacy_solo = favorites + [r for r in DEFAULT_ROOMS[PRACTICE_SOLO] if r not in favorites]
    result = {}
    for practice, default in ((PRACTICE_SOLO, legacy_solo), (PRACTICE_ENSEMBLE, DEFAULT_ROOMS[PRACTICE_ENSEMBLE])):
        rooms = [r for r in chosen.get(practice, []) if r in VERIFIED_ROOMS]
        result[practice] = rooms or default
    return result


def rooms_for_plan(chosen: list[str], minutes: int) -> tuple[list[str], list[str]]:
    """この予定で試す部屋（最大5室）と、利用時間が長すぎて外した部屋を返す。"""
    usable = [r for r in chosen if r in VERIFIED_ROOMS]
    too_long = [r for r in usable if minutes > max_minutes(r)]
    to_try = [r for r in usable if r not in too_long][:MAX_ROOMS_TO_TRY]
    return to_try, too_long


def needs_members(rooms: list[str]) -> bool:
    return any(r in NEEDS_MEMBERS for r in rooms)
