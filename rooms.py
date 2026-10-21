"""部屋の名前と予約サイトの番号（event_id）。予約状況の画面の一覧（list_rooms.py）から写したもの。"""

from booking_rules import PRACTICE_ENSEMBLE, PRACTICE_SOLO

# 3階の部屋（個人練習でどこでも使う）。番号の小さい部屋から順に試す
ROOMS_3F = {
    "E312": 116, "E313": 117, "E320": 120, "E321": 121, "E322": 122, "E323": 233,
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


def event_id_of(room: str) -> int:
    key = room.upper().removesuffix("室")
    if key not in ALL_ROOMS:
        raise ValueError(f"{room} は登録されていない部屋です（3階の部屋とE452のみ）")
    return ALL_ROOMS[key]
