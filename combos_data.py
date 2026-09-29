# combos_data.py

COMBOS = [
    {"name": "黑白双煞", "members": ["张顺", "李逵"], "atk": "avg + 9", "def": "avg + 35", "special": None},
    {"name": "水军兄弟", "members": ["阮小二", "阮小五"], "atk": "avg + 11", "def": "avg + 45", "special": None},
    {"name": "水军兄弟", "members": ["阮小二", "阮小七"], "atk": "avg + 11", "def": "avg + 45", "special": None},
    {"name": "水军兄弟", "members": ["阮小五", "阮小七"], "atk": "avg + 10", "def": "avg + 30", "special": None},
    {"name": "水军兄弟", "members": ["张横", "张顺"], "atk": "avg + 10", "def": "avg + 30", "special": None},
    {"name": "水军三兄弟", "members": ["阮小二", "阮小五", "阮小七"], "atk": "avg + 58/3", "def": "avg + 85", "special": "bomb_eater"},
    {"name": "打猎兄弟", "members": ["解珍", "解宝"], "atk": "avg + 13", "def": "avg + 25", "special": None},
    {"name": "智多星", "members": ["吴用", "*"], "atk": "wu_yong_atk + 10", "def": "other_def", "special": "wu_yong"},
    {"name": "风流威猛", "members": ["花荣", "徐宁"], "atk": "avg + 21", "def": "avg + 23.5", "special": "bomb_eater"},
    {"name": "五虎将", "members": ["关胜", "林冲", "秦明", "呼延灼", "董平"], "atk": "sum", "def": "sum", "special": "bomb_eater_steal3"},
    {"name": "八虎骑", "members": ["花荣", "徐宁", "杨志", "索超", "张清", "朱仝", "史进", "穆弘"], "atk": "sum", "def": "sum", "special": "bomb_eater_steal3"},
]

SPECIAL_CARDS = {
    "bomb": ["白胜", "孙二娘"],
    "beauty": ["扈三娘"],
    "handsome": ["林冲", "柴进", "燕青", "花荣", "徐宁"],
    "songjiang": ["宋江"],
}
