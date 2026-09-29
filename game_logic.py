# game_logic.py
import random
import math
from cards_data import CARDS, CARD_BY_NAME
from combos_data import COMBOS, SPECIAL_CARDS

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

def upgrade_cost(level):
    return level

def can_upgrade(level, duplicate_count):
    return duplicate_count >= upgrade_cost(level)

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

def calc_combo_stats(cards):
    if len(cards) == 1:
        c = cards[0]
        return c["atk"], c["def"], None
    names = [c["name"] for c in cards]
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
