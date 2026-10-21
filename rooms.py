"""部屋の名前と予約サイトの番号（event_id）。予約状況の画面の一覧（list_rooms.py）から写したもの。"""

from booking_rules import PRACTICE_ENSEMBLE, PRACTICE_SOLO

# 3階の部屋（個人練習でどこでも使う）。番号の小さい部屋から順に試す
# E312・E313 はアンサンブル用の部屋なので、個人練習の候補に入れない
ROOMS_3F = {
    "E320": 120, "E321": 121, "E322": 122, "E323": 233,
    "E324": 124, "E325": 125, "E326": 126, "E327": 127, "E328": 128, "E329": 129,
    "E330": 130, "E331": 131, "E332": 132, "E333": 133, "E334": 134, "E335": 135,
    "E336": 136, "E337": 137, "E338": 138, "E341": 139, "E342": 140, "E343": 141,
    "E344": 142, "E345": 143, "E346": 144, "E351": 145, "E352": 146, "E353": 147,
    "E354": 148, "E355": 149, "E356": 150,
}

# TBの部屋（アンサンブルで使う）
ROOMS_TB = {"E452": 291}

ALL_ROOMS = {**ROOMS_3F, **ROOMS_TB}

CANDIDATES = {PRACTICE_SOLO: ROOMS_3F, PRACTICE_ENSEMBLE: ROOMS_TB}

# E452 は利用時間が2時間まで、注意事項の確認と同時利用者の入力が必須
MAX_MINUTES = {291: 120}
NEEDS_MEMBERS = {291}


def room_key(room: str) -> str:
    key = room.strip().upper().removesuffix("室")
    if key not in ALL_ROOMS:
        raise ValueError(f"{room} は登録されていない部屋です（E312・E313以外の3階の部屋とE452のみ）")
    return key


def event_id_of(room: str) -> int:
    return ALL_ROOMS[room_key(room)]


def candidates(practice_type: str, preferred: list[str], limit: int) -> list[str]:
    """試す部屋を順に並べる。preferred（よく使う部屋）を先にし、残りは番号順。最大 limit 室。"""
    rooms = CANDIDATES[practice_type]
    ordered = [room_key(r) for r in preferred]
    for r in ordered:
        if r not in rooms:
            raise ValueError(f"{r} は{practice_type}の候補ではありません")
    ordered += [r for r in rooms if r not in ordered]
    return list(dict.fromkeys(ordered))[:limit]
