# combos_data.py
# 搏卡/挑战组合技数据
#
# atk / def 支持三种格式：
#   - "avg + X"      平均值 + X
#   - "卡名.atk + X" 指定卡的基础攻击/防御 + X（含星级加成）
#   - 数字           固定值

COMBOS = [
    {"name": "黑白双煞", "members": ["张顺", "李逵"], "atk": "李逵.atk + 5", "def": "张顺.def + 50", "special": None},
    {"name": "水军兄弟", "members": ["阮小二", "阮小五"], "atk": "阮小二.atk + 10", "def": "阮小五.def + 45", "special": None},
    {"name": "水军兄弟", "members": ["阮小二", "阮小七"], "atk": "阮小二.atk + 10", "def": "阮小七.def + 45", "special": None},
    {"name": "水军兄弟", "members": ["阮小五", "阮小七"], "atk": "阮小五.atk + 10", "def": "阮小七.def + 30", "special": None},
    {"name": "水军兄弟", "members": ["张横", "张顺"], "atk": "张横.atk + 10", "def": "张顺.def + 30", "special": None},
    {"name": "水军三兄弟", "members": ["阮小二", "阮小五", "阮小七"], "atk": 200, "def": 200, "special": "bomb_eater"},
    {"name": "打猎兄弟", "members": ["解珍", "解宝"], "atk": "解珍.atk + 13", "def": "解宝.def + 25", "special": None},
    {"name": "智多星", "members": ["吴用", "*"], "atk": "wu_yong_atk + 10", "def": "other_def", "special": "wu_yong"},
    {"name": "风流威猛", "members": ["花荣", "徐宁"], "atk": 300, "def": 300, "special": "bomb_eater"},
    {"name": "五虎将", "members": ["关胜", "林冲", "秦明", "呼延灼", "董平"], "atk": 999, "def": 999, "special": "bomb_eater_steal1"},
    {"name": "八虎骑", "members": ["花荣", "徐宁", "杨志", "索超", "张清", "朱仝", "史进", "穆弘"], "atk": 999, "def": 999, "special": "bomb_eater_steal1"},
]

SPECIAL_CARDS = {
    "bomb": ["白胜", "孙二娘"],
    "beauty": ["扈三娘"],
    "handsome": ["林冲", "柴进", "燕青", "花荣", "徐宁"],
    "songjiang": ["宋江"],
}
