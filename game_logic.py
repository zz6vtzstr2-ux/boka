# game_logic.py
import random
import math
from cards_data import CARDS, CARD_BY_NAME
from combos_data import COMBOS, SPECIAL_CARDS

# ========== 抽卡 ==========
def draw_card():
    """抽一张卡，返回 (卡片列表, 结果类型)"""
    roll = random.random()
    if roll < 0.01:
        return [], "empty"  # 1% 空包
    elif roll < 0.03:
        card = random.choice(CARDS)
        return [card, card], "double"  # 2% 双黄蛋
    else:
        card = random.choice(CARDS)
        return [card], "normal"

# ========== 升星 ==========
def get_level(star, quality):
    quality_index = {"白": 0, "绿": 1, "蓝": 2, "紫": 3, "橙": 4}
    return quality_index[quality] * 5 + star

def get_quality_star(level):
    qualities = ["白", "绿", "蓝", "紫", "橙"]
    quality_index = (level - 1) // 5
    star = (level - 1) % 5 + 1
    return qualities[quality_index], star

def upgrade_cost(level):
    return level

def can_upgrade(level, duplicate_count):
    return duplicate_count >= upgrade_cost(level)

# ========== 建筑产出 ==========
def building_output(card, attr_key, level):
    base = card[attr_key]
    multiplier = 1.0 + level * 0.01
    return base * multiplier

def total_output(buildings, building_cards, deputies=None):
    attr_map = {1: "lead", 2: "might", 3: "intel", 4: "politics", 5: "charm"}
    total = 0
    for bid, attr in attr_map.items():
        level = buildings.get(str(bid), 0)
        card_id = building_cards.get(str(bid))
        if card_id:
            card = next((c for c in CARDS if c["id"] == card_id), None)
            if card:
                total += building_output(card, attr, level)
        if deputies and str(bid) in deputies:
            dep_id = deputies[str(bid)]
            dep_card = next((c for c in CARDS if c["id"] == dep_id), None)
            if dep_card:
                total += building_output(dep_card, attr, level)
    return total

# ========== 战斗结算 ==========
def calc_combo_stats(cards):
    """计算一组卡的攻防（普通卡相加，组合卡按公式）"""
    if len(cards) == 1:
        c = cards[0]
        return c["atk"], c["def"], None

    names = [c["name"] for c in cards]

    # 五虎将、八虎骑：攻防固定 999
    for combo in COMBOS:
        members = combo["members"]
        if combo["name"] in ("五虎将", "八虎骑") and set(members) == set(names):
            return 999, 999, combo["name"]

    for combo in COMBOS:
        members = combo["members"]
        if "*" in members:
            if members[0] in names and len(cards) == 2:
                return calc_wu_yong(cards), combo["name"]
        elif set(members) == set(names):
            return calc_combo(combo, cards), combo["name"]

    return None, None, None

def calc_wu_yong(cards):
    wu = next((c for c in cards if c["name"] == "吴用"), None)
    other = next((c for c in cards if c["name"] != "吴用"), None)
    if wu and other:
        return wu["atk"] + 10, other["def"]
    return 0, 0

def calc_combo(combo, cards):
    atk_formula = combo["atk"]
    def_formula = combo["def"]
    if atk_formula == "sum":
        return sum(c["atk"] for c in cards), sum(c["def"] for c in cards)
    if "avg" in atk_formula:
        avg_atk = sum(c["atk"] for c in cards) / len(cards)
        avg_def = sum(c["def"] for c in cards) / len(cards)
        if "58/3" in atk_formula:
            atk_bonus = 58 / 3
        else:
            atk_bonus = float(atk_formula.split("+")[1].strip())
        def_bonus = float(def_formula.split("+")[1].strip())
        return round(avg_atk + atk_bonus, 1), round(avg_def + def_bonus, 1)
    return 0, 0

# ========== 天梯积分 ==========
def calc_score_change(my_score, rank, total_players, base_scores, opp_avg_score):
    base = base_scores.get(rank, 0)
    if base == 0:
        return 0
    k = 0.5
    ratio = (opp_avg_score + 1000) / (my_score + 1000)
    coef = 1 + k * math.log(ratio)
    coef = max(0.5, min(3.0, coef))
    if base > 0:
        return round(base * coef)
    else:
        return round(base / coef)

# ========== 挑战建材 ==========
def challenge_materials(level, win_index):
    """计算挑战单胜建材"""
    if win_index >= 10:
        decay = 0.15
    else:
        decay = [1.0, 0.9, 0.8, 0.7, 0.6, 0.5, 0.4, 0.3, 0.2, 0.15][win_index]
    coef = 1.0 + (level - 1) / 500 * 1.8
    raw = 18 * coef * decay
    integer = int(raw)
    fraction = raw - integer
    if random.random() < fraction:
        return integer + 1
    return integer
