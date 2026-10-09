# game_logic.py
import random
import math
from cards_data import CARDS, CARD_BY_NAME
from combos_data import COMBOS, SPECIAL_CARDS
from bonds_data import (
    RELATION_BONDS, REGION_BONDS, REGION_BONUS_BY_COUNT,
    POSITION_BONDS, POSITION_BONUS, ENEMY_BONDS,
)

# ========== 抽卡 ==========
def draw_card():
    roll = random.random()
    if roll < 0.01:
        return [], "empty"
    elif roll < 0.03:
        card = random.choice(CARDS)
        return [card, card], "double"
    else:
        card = random.choice(CARDS)
        return [card], "normal"

# ========== 星级 / 等级 ==========
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

def star_bonus(level):
    """
    星级加成：升一级 +1 攻 +1 防。
    level 1 = 原始攻防（+0/+0）
    level 25 = +24/+24
    """
    bonus = max(0, level - 1)
    return bonus, bonus

def card_with_level(card, level=1):
    """返回卡的攻防（含星级加成）"""
    atk_b, def_b = star_bonus(level)
    return card["atk"] + atk_b, card["def"] + def_b

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

# ========== 组合技计算 ==========
def _resolve_formula(formula, cards, combo_members):
    """
    解析 atk / def 公式。
    formula 可能是：
      - 数字：直接返回
      - "avg + X"：平均值 + X
      - "卡名.atk + X"：指定卡的攻击（含星级）+ X
      - "卡名.def + X"：指定卡的防御（含星级）+ X
      - "wu_yong_atk + 10"：吴用 atk + 10（旧兼容）
      - "other_def"：另一张卡的 def（旧兼容）
    cards 是 list of dict（已含 level 字段）
    """
    # 数字
    if isinstance(formula, (int, float)):
        return float(formula)

    if not isinstance(formula, str):
        return 0.0

    s = formula.strip()

    # 旧兼容：wu_yong_atk + 10
    if s == "wu_yong_atk + 10":
        wu = next((c for c in cards if c["name"] == "吴用"), None)
        if wu:
            a, _ = card_with_level(wu, wu.get("level", 1))
            return a + 10
        return 0.0

    if s == "other_def":
        other = next((c for c in cards if c["name"] != "吴用"), None)
        if other:
            _, d = card_with_level(other, other.get("level", 1))
            return d
        return 0.0

    # avg + X
    if s.startswith("avg"):
        try:
            bonus = float(s.split("+")[1].strip())
        except Exception:
            bonus = 0.0
        atks = [card_with_level(c, c.get("level", 1))[0] for c in cards]
        return sum(atks) / len(atks) + bonus

    # 卡名.atk + X / 卡名.def + X
    if ".atk" in s or ".def" in s:
        # 解析 "李逵.atk + 5"
        parts = s.split(".")
        card_name = parts[0].strip()
        rest = parts[1]  # "atk + 5" 或 "def + 50"
        # 找目标卡
        target = None
        for c in cards:
            if c["name"] == card_name:
                target = c
                break
        if not target:
            return 0.0
        # 解析加成
        try:
            bonus = float(rest.split("+")[1].strip())
        except Exception:
            bonus = 0.0
        # 取对应属性
        if "atk" in rest:
            base_val, _ = card_with_level(target, target.get("level", 1))
        else:
            _, base_val = card_with_level(target, target.get("level", 1))
        return base_val + bonus

    return 0.0


def calc_combo_stats(cards):
    """
    cards: list of dict（每张卡已含 level 字段）
    返回 (atk, def, combo_name) 或 (None, None, None)
    """
    if not cards:
        return None, None, None

    if len(cards) == 1:
        a, d = card_with_level(cards[0], cards[0].get("level", 1))
        return a, d, None

    names = [c["name"] for c in cards]

    # 优先检查特殊组合（按名称集合严格匹配）
    for combo in COMBOS:
        members = combo["members"]
        if "*" in members:
            continue
        if set(members) == set(names):
            atk = _resolve_formula(combo["atk"], cards, members)
            dfn = _resolve_formula(combo["def"], cards, members)
            return atk, dfn, combo["name"]

    # 智多星（吴用 + 任意 1 张）
    for combo in COMBOS:
        members = combo["members"]
        if "*" in members:
            # 处理 吴用 + 任意
            if members[0] in names and len(cards) == 2:
                # 智多星
                wu = next((c for c in cards if c["name"] == "吴用"), None)
                other = next((c for c in cards if c["name"] != "吴用"), None)
                if wu and other:
                    a, _ = card_with_level(wu, wu.get("level", 1))
                    _, d = card_with_level(other, other.get("level", 1))
                    return a + 10, d, combo["name"]

    return None, None, None

# ========== 天梯积分（搏卡） ==========
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

# ========== 世界 Boss 疲劳 ==========
def fatigue_coef(times):
    return 1.0 / (1.0 + times * 0.3)

def real_attr(value, times):
    return int(value * fatigue_coef(times))

# ========== 世界 Boss 伤害 ==========
def boss_card_damage(card, weak_attr, fatigue_times, bond_bonus=0.0):
    attrs = ["lead", "might", "intel", "politics", "charm"]
    main_val = real_attr(card[weak_attr], fatigue_times)
    other_sum = sum(real_attr(card[a], fatigue_times) for a in attrs if a != weak_attr)
    damage = main_val * 3.0 + other_sum * 1.0
    damage = damage * (1 + bond_bonus)
    return int(damage)

def boss_deck_damage(deck, weak_attr, fatigue_data, bond_bonus=0.0):
    total = 0
    for card in deck:
        times = fatigue_data.get(str(card["id"]), 0)
        total += boss_card_damage(card, weak_attr, times, bond_bonus)
    return total

# ========== 世界 Boss 血量 ==========
def boss_hp(week_num):
    return int((30 + (week_num - 1) * 1.2) * 10000)

# ========== 羁绊计算 ==========
def calc_relation_bonus(deck_names):
    result = {}
    best = 0.0
    best_names = []
    for bond in RELATION_BONDS:
        for group in bond["groups"]:
            if all(n in deck_names for n in group):
                bonus_rule = bond["bonus"]
                if isinstance(bonus_rule, dict):
                    cnt = len(group)
                    bonus = bonus_rule.get(cnt, bonus_rule.get(max(bonus_rule.keys()), 0))
                else:
                    bonus = bonus_rule
                if bonus > best:
                    best = bonus
                    best_names = list(group)
    if best > 0:
        for n in best_names:
            result[n] = best
    return result

def calc_region_bonus(deck_names):
    result = {}
    best = 0.0
    best_names = []
    for region in REGION_BONDS:
        members_in_deck = [n for n in region["members"] if n in deck_names]
        cnt = len(members_in_deck)
        if cnt < 2:
            continue
        bonus = REGION_BONUS_BY_COUNT.get(min(cnt, 5), 0)
        if bonus > best:
            best = bonus
            best_names = members_in_deck
    if best > 0:
        for n in best_names:
            result[n] = best
    return result

def calc_position_bonus(deck_names):
    result = {}
    best = 0.0
    best_names = []
    for position in POSITION_BONDS:
        members_in_deck = [n for n in position["members"] if n in deck_names]
        cnt = len(members_in_deck)
        if cnt < 2:
            continue
        tier = position.get("tier", "normal")
        bonus_table = POSITION_BONUS.get(tier, POSITION_BONUS["normal"])
        bonus = bonus_table.get(min(cnt, 5), 0)
        if bonus > best:
            best = bonus
            best_names = members_in_deck
    if best > 0:
        for n in best_names:
            result[n] = best
    return result

def calc_enemy_bonus(deck_names):
    result = {}
    worst = 0.0
    worst_names = []
    for bond in ENEMY_BONDS:
        for group in bond["groups"]:
            if all(n in deck_names for n in group):
                if bond["penalty"] > worst:
                    worst = bond["penalty"]
                    worst_names = list(group)
    if worst > 0:
        for n in worst_names:
            result[n] = worst
    return result

def calc_bond_bonus_for_deck(deck):
    deck_names = [c["name"] for c in deck]
    rel = calc_relation_bonus(deck_names)
    reg = calc_region_bonus(deck_names)
    pos = calc_position_bonus(deck_names)
    ene = calc_enemy_bonus(deck_names)
    result = {}
    all_names = set(rel.keys()) | set(reg.keys()) | set(pos.keys()) | set(ene.keys())
    for n in all_names:
        bonus = rel.get(n, 0) + reg.get(n, 0) + pos.get(n, 0)
        penalty = ene.get(n, 0)
        result[n] = (bonus, penalty)
    return result

def boss_deck_damage_with_bond(deck, weak_attr, fatigue_data):
    bond_map = calc_bond_bonus_for_deck(deck)
    total = 0
    for card in deck:
        times = fatigue_data.get(str(card["id"]), 0)
        bonus, penalty = bond_map.get(card["name"], (0.0, 0.0))
        dmg = boss_card_damage(card, weak_attr, times, 0.0)
        multiplier = 1.0 + bonus - penalty
        multiplier = max(0.0, multiplier)
        total += int(dmg * multiplier)
    return total
