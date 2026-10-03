# app.py
import os
import random
import math
from datetime import datetime, timedelta, date
from flask import Flask, render_template, request, jsonify, redirect, url_for
from flask_login import LoginManager, login_user, login_required, logout_user, current_user
from models import db, User
from cards_data import CARDS, CARD_BY_NAME, CARD_BY_ID
from combos_data import COMBOS, SPECIAL_CARDS
from game_logic import (
    draw_card, get_quality_star, upgrade_cost,
    building_output, total_output, calc_combo_stats,
    calc_score_change, challenge_materials,
    fatigue_coef, real_attr, boss_card_damage, boss_deck_damage, boss_hp
)

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-secret-change-me')

database_url = os.environ.get('DATABASE_URL', 'sqlite:///game.db')
if database_url.startswith('postgres://'):
    database_url = database_url.replace('postgres://', 'postgresql://', 1)
app.config['SQLALCHEMY_DATABASE_URI'] = database_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db.init_app(app)

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

ATTR_MAP = {1: "lead", 2: "might", 3: "intel", 4: "politics", 5: "charm"}
ATTR_NAMES = {1: "聚义厅", 2: "演武场", 3: "天机阁", 4: "政务堂", 5: "聚贤庄"}
ATTR_CN = {"lead": "统率", "might": "武力", "intel": "智力", "politics": "政治", "charm": "魅力"}

BOSS_LIST = [
    {"name": "方腊", "troop": "先锋营"},
    {"name": "高俅", "troop": "中军帐"},
    {"name": "童贯", "troop": "军机处"},
    {"name": "蔡京", "troop": "粮草营"},
    {"name": "辽国元帅", "troop": "招贤馆"},
]

# ========== 登录 ==========
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        user = User.query.filter_by(username=username).first()
        if user and user.check_password(password):
            login_user(user)
            return redirect(url_for('game'))
        return render_template('login.html', error='账号或密码错误')
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

# ========== 主页 ==========
@app.route('/')
@login_required
def game():
    return render_template('game.html',
                           username=current_user.username,
                           nickname=current_user.nickname or current_user.username,
                           gold=current_user.gold,
                           silver=current_user.silver,
                           copper=current_user.copper)

# ========== 抽卡 ==========
@app.route('/draw')
@login_required
def draw_page():
    return render_template('draw.html',
                           gold=current_user.gold,
                           username=current_user.username,
                           nickname=current_user.nickname or current_user.username,
                           silver=current_user.silver,
                           copper=current_user.copper)

@app.route('/draw_card', methods=['POST'])
@login_required
def draw_card_route():
    if not current_user.got_starter:
        current_user.got_starter = True
        db.session.commit()
        cards, result_type = draw_card()
        collection = current_user.get_collection()
        first_time = []
        for card in cards:
            cid = str(card["id"])
            if cid not in collection:
                first_time.append(card["name"])
            collection[cid] = collection.get(cid, 0) + 1
        current_user.set_collection(collection)
        db.session.commit()
        if result_type == "empty":
            return jsonify({"type": "empty", "message": "厂商忘放卡了"})
        if result_type == "double":
            return jsonify({"type": "double", "cards": cards, "message": "双黄蛋", "first_time": first_time})
        return jsonify({"type": "normal", "cards": cards, "first_time": first_time})

    if current_user.gold < 2:
        return jsonify({"error": "金币不足"}), 400
    current_user.gold -= 2
    cards, result_type = draw_card()
    if result_type == "empty":
        db.session.commit()
        return jsonify({"type": "empty", "message": "厂商忘放卡了"})
    collection = current_user.get_collection()
    first_time = []
    for card in cards:
        cid = str(card["id"])
        if cid not in collection:
            first_time.append(card["name"])
        collection[cid] = collection.get(cid, 0) + 1
    current_user.set_collection(collection)
    db.session.commit()
    if result_type == "double":
        return jsonify({"type": "double", "cards": cards, "message": "双黄蛋", "first_time": first_time})
    return jsonify({"type": "normal", "cards": cards, "first_time": first_time})

# ========== 收藏册 ==========
@app.route('/collection')
@login_required
def collection():
    coll = current_user.get_collection()
    cards_with_count = []
    for card in CARDS:
        cid = str(card["id"])
        count = coll.get(cid, 0)
        if count > 0:
            cards_with_count.append({**card, "count": count})
    return render_template('collection.html',
                           cards=cards_with_count,
                           all_cards=CARDS,
                           username=current_user.username,
                           nickname=current_user.nickname or current_user.username,
                           gold=current_user.gold,
                           silver=current_user.silver,
                           copper=current_user.copper)

@app.route('/upgrade', methods=['POST'])
@login_required
def upgrade():
    card_id = str(request.json.get('card_id'))
    coll = current_user.get_collection()
    count = coll.get(card_id, 0)
    if count < 2:
        return jsonify({"error": "同名卡不足"}), 400
    level = count
    cost = upgrade_cost(level)
    if count < cost + 1:
        return jsonify({"error": "同名卡不足"}), 400
    coll[card_id] = count - cost
    current_user.set_collection(coll)
    db.session.commit()
    return jsonify({"success": True, "new_count": coll[card_id]})

@app.route('/donate', methods=['POST'])
@login_required
def donate():
    card_id = str(request.json.get('card_id'))
    coll = current_user.get_collection()
    count = coll.get(card_id, 0)
    if count < 2:
        return jsonify({"error": "重复卡不足"}), 400
    coll[card_id] = count - 1
    current_user.set_collection(coll)
    current_user.gold += 1
    db.session.commit()
    return jsonify({"success": True, "gold": current_user.gold})

# ========== 班级收藏册 ==========
@app.route('/class_collection')
@login_required
def class_collection():
    all_users = User.query.all()
    class_cards = {}
    for u in all_users:
        coll = u.get_collection()
        for cid, cnt in coll.items():
            if cid not in class_cards:
                class_cards[cid] = {"donor": u.nickname or u.username, "donated_at": "20260101"}
    cards = []
    for card in CARDS:
        cid = str(card["id"])
        if cid in class_cards:
            cards.append({**card, "owned": True,
                          "donor": class_cards[cid]["donor"],
                          "donated_at": class_cards[cid]["donated_at"]})
        else:
            cards.append({**card, "owned": False})
    return render_template('class_collection.html',
                           cards=cards,
                           username=current_user.username,
                           nickname=current_user.nickname or current_user.username,
                           gold=current_user.gold,
                           silver=current_user.silver,
                           copper=current_user.copper)

# ========== 挂机建筑（家园） ==========
@app.route('/buildings')
@login_required
def buildings():
    buildings_data = current_user.get_buildings()
    building_cards = current_user.get_building_cards()
    deputies = current_user.get_deputies()
    coll = current_user.get_collection()
    owned = [c for c in CARDS if str(c["id"]) in coll]
    result = []
    total = 0
    for bid, attr in ATTR_MAP.items():
        level = buildings_data.get(str(bid), 0)
        card_id = building_cards.get(str(bid))
        card = CARD_BY_ID.get(card_id) if card_id else None
        dep_id = deputies.get(str(bid))
        dep_card = CARD_BY_ID.get(dep_id) if dep_id else None
        output = 0
        if card:
            output += building_output(card, attr, level)
        if dep_card:
            output += building_output(dep_card, attr, level)
        total += output
        max_hours = 8 + (level // 10)
        accumulated = 0
        progress = 0
        result.append({"bid": bid, "name": ATTR_NAMES[bid], "attr": ATTR_CN[attr],
                       "level": level, "card": card, "deputy": dep_card,
                       "output": int(output), "max_hours": max_hours,
                       "accumulated": accumulated, "progress": progress})
    return render_template('buildings.html',
                           buildings=result,
                           cards=owned,
                           materials=current_user.materials,
                           total_output=int(total),
                           username=current_user.username,
                           nickname=current_user.nickname or current_user.username,
                           gold=current_user.gold,
                           silver=current_user.silver,
                           copper=current_user.copper)

@app.route('/collect_all', methods=['POST'])
@login_required
def collect_all():
    buildings_data = current_user.get_buildings()
    building_cards = current_user.get_building_cards()
    deputies = current_user.get_deputies()
    output = total_output(buildings_data, building_cards, deputies)
    copper = int(output * 24)
    silver = copper // 100
    gold = silver // 100
    copper = copper % 100
    silver = silver % 100
    current_user.copper += copper
    current_user.silver += silver
    current_user.gold += gold
    current_user.last_collect = datetime.now()
    db.session.commit()
    return jsonify({"copper": copper, "silver": silver, "gold": gold})

@app.route('/collect_one', methods=['POST'])
@login_required
def collect_one():
    bid = str(request.json.get('bid'))
    buildings_data = current_user.get_buildings()
    building_cards = current_user.get_building_cards()
    deputies = current_user.get_deputies()
    attr_map = {1: "lead", 2: "might", 3: "intel", 4: "politics", 5: "charm"}
    attr = attr_map.get(int(bid))
    if not attr:
        return jsonify({"error": "无效建筑"}), 400
    level = buildings_data.get(bid, 0)
    card_id = building_cards.get(bid)
    card = CARD_BY_ID.get(card_id) if card_id else None
    output = 0
    if card:
        output += building_output(card, attr, level)
    dep_id = deputies.get(bid)
    dep_card = CARD_BY_ID.get(dep_id) if dep_id else None
    if dep_card:
        output += building_output(dep_card, attr, level)
    copper = int(output * 24)
    silver = copper // 100
    gold = silver // 100
    copper = copper % 100
    silver = silver % 100
    current_user.copper += copper
    current_user.silver += silver
    current_user.gold += gold
    db.session.commit()
    return jsonify({"copper": copper, "silver": silver, "gold": gold})

@app.route('/upgrade_building', methods=['POST'])
@login_required
def upgrade_building():
    bid = str(request.json.get('bid'))
    buildings_data = current_user.get_buildings()
    level = buildings_data.get(bid, 0)
    if level >= 100:
        return jsonify({"error": "已满级"}), 400
    cost = (level + 1) * 10
    if current_user.materials < cost:
        return jsonify({"error": "建材不足"}), 400
    current_user.materials -= cost
    buildings_data[bid] = level + 1
    current_user.set_buildings(buildings_data)
    db.session.commit()
    return jsonify({"success": True, "new_level": level + 1})

@app.route('/set_building_card', methods=['POST'])
@login_required
def set_building_card():
    bid = str(request.json.get('bid'))
    card_id = request.json.get('card_id')
    building_cards = current_user.get_building_cards()
    if card_id:
        building_cards[bid] = card_id
    else:
        building_cards.pop(bid, None)
    current_user.set_building_cards(building_cards)
    db.session.commit()
    return jsonify({"success": True})

# ========== 挑战 ==========
@app.route('/challenge')
@login_required
def challenge():
    level = request.args.get('level', current_user.challenge_level)
    return render_template('challenge.html',
                           level=int(level),
                           username=current_user.username,
                           nickname=current_user.nickname or current_user.username,
                           gold=current_user.gold,
                           silver=current_user.silver,
                           copper=current_user.copper)

@app.route('/challenge/start', methods=['POST'])
@login_required
def challenge_start():
    level = request.json.get('level', current_user.challenge_level)
    ai_cards = random.sample(CARDS, 6)
    return jsonify({"ai_cards": ai_cards, "level": level})

@app.route('/challenge/result', methods=['POST'])
@login_required
def challenge_result():
    win = request.json.get('win', False)
    level = request.json.get('level', current_user.challenge_level)
    if win:
        if level >= current_user.challenge_level:
            current_user.challenge_level = level + 1
        win_index = current_user.daily_challenge_wins
        materials = challenge_materials(level, win_index)
        current_user.materials += materials
        current_user.daily_challenge_wins += 1
        db.session.commit()
        return jsonify({"success": True, "materials": materials, "new_level": current_user.challenge_level})
    return jsonify({"success": False})

# ========== 搏卡 ==========
@app.route('/boka')
@login_required
def boka():
    return render_template('boka.html',
                           username=current_user.username,
                           nickname=current_user.nickname or current_user.username,
                           gold=current_user.gold,
                           silver=current_user.silver,
                           copper=current_user.copper)

@app.route('/boka/create', methods=['POST'])
@login_required
def boka_create():
    room_id = ''.join(random.choices('ABCDEFGHJKLMNPQRSTUVWXYZ23456789', k=6))
    return jsonify({"room_id": room_id})

# ========== 世界 Boss ==========
@app.route('/world_boss')
@login_required
def world_boss():
    today = date.today()
    if current_user.boss_fatigue_reset != today:
        current_user.set_boss_fatigue({})
        current_user.boss_fatigue_reset = today
        db.session.commit()

    boss = random.choice(BOSS_LIST)
    weak_attr = random.choice(list(ATTR_CN.keys()))
    hp = boss_hp(current_user.boss_week)

    return render_template('world_boss.html',
                           boss=boss,
                           weak_attr=weak_attr,
                           weak_attr_cn=ATTR_CN[weak_attr],
                           hp=hp,
                           username=current_user.username,
                           nickname=current_user.nickname or current_user.username,
                           gold=current_user.gold,
                           silver=current_user.silver,
                           copper=current_user.copper)

@app.route('/world_boss/fatigue', methods=['POST'])
@login_required
def world_boss_fatigue():
    card_id = str(request.json.get('card_id'))
    fatigue = current_user.get_boss_fatigue()
    times = fatigue.get(card_id, 0)
    fatigue[card_id] = times + 1
    current_user.set_boss_fatigue(fatigue)
    db.session.commit()
    return jsonify({"success": True, "times": times + 1})

@app.route('/world_boss/damage', methods=['POST'])
@login_required
def world_boss_damage():
    deck = request.json.get('deck', [])
    weak_attr = request.json.get('weak_attr')
    fatigue = current_user.get_boss_fatigue()
    damage = boss_deck_damage(deck, weak_attr, fatigue)
    return jsonify({"damage": damage})

# ========== 数据页 ==========
@app.route('/data')
@login_required
def data_page():
    return render_template('data.html',
                           username=current_user.username,
                           nickname=current_user.nickname or current_user.username,
                           gold=current_user.gold,
                           silver=current_user.silver,
                           copper=current_user.copper)

# ========== 我的资料 ==========
@app.route('/profile')
@login_required
def profile():
    trophies = current_user.get_champion_months()
    return render_template('profile.html',
                           username=current_user.username,
                           nickname=current_user.nickname or current_user.username,
                           gold=current_user.gold,
                           silver=current_user.silver,
                           copper=current_user.copper,
                           trophies=trophies)

# ========== 启动 ==========
with app.app_context():
    db.create_all()

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=int(os.getenv('PORT', 5000)))
