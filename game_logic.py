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
    if len(cards) == 1:
        c = cards[0]
        return c["atk"], c["def"], None

    names = [c["name"] for c in cards]

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

# ========== 羁绊计算 ==========
def calc_relation_bonus(deck_names):
    """
    关系类：返回 {card_name: bonus}，只对参与羁绊的卡加成。
    同类只取最高加成。
    """
    result = {}
    best = 0.0
    best_names = []

    for bond in RELATION_BONDS:
        for group in bond["groups"]:
            # 整组都在卡组里，才算触发
            if all(n in deck_names for n in group):
                bonus_rule = bond["bonus"]
                if isinstance(bonus_rule, dict):
                    # 按人数取加成
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
    """
    地域类：返回 {card_name: bonus}，只对参与羁绊的卡加成。
    同类只取最高加成。
    """
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
    """
    职位类：返回 {card_name: bonus}，只对参与羁绊的卡加成。
    同类只取最高加成。
    """
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
    """
    仇敌类：返回 {card_name: penalty}（正数表示要减掉的百分比）。
    同类只取最重的一项。
    """
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
    """
    输入：deck 是卡的字典列表（每张卡有 name 字段）
    输出：{card_name: (bonus, penalty)}，bonus 为正加成比例，penalty 为要减掉的比例
    只有触发了羁绊的卡才在 dict 里。
    """
    deck_names = [c["name"] for c in deck]

    rel = calc_relation_bonus(deck_names)
    reg = calc_region_bonus(deck_names)
    pos = calc_position_bonus(deck_names)
    ene = calc_enemy_bonus(deck_names)

    # 汇总：每张卡可能有多个加成/减益
    result = {}
    all_names = set(rel.keys()) | set(reg.keys()) | set(pos.keys()) | set(ene.keys())
    for n in all_names:
        bonus = rel.get(n, 0) + reg.get(n, 0) + pos.get(n, 0)
        penalty = ene.get(n, 0)
        result[n] = (bonus, penalty)
    return result

def boss_deck_damage_with_bond(deck, weak_attr, fatigue_data):
    """
    计算卡组对 Boss 的伤害，含羁绊加成。
    deck: 卡的字典列表
    weak_attr: 今日弱点属性 key
    fatigue_data: {card_id_str: times}
    """
    bond_map = calc_bond_bonus_for_deck(deck)
    total = 0
    for card in deck:
        times = fatigue_data.get(str(card["id"]), 0)
        bonus, penalty = bond_map.get(card["name"], (0.0, 0.0))
        # 基础伤害
        dmg = boss_card_damage(card, weak_attr, times, 0.0)
        # 加成 - 减益
        multiplier = 1.0 + bonus - penalty
        multiplier = max(0.0, multiplier)
        total += int(dmg * multiplier)
    return total
    
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
