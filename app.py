# app.py
import os
import random
import math
from datetime import datetime, timedelta, date
from flask import Flask, render_template, request, jsonify, redirect, url_for, send_from_directory
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
if database_url.startswith('postgresql://'):
    database_url = database_url.replace('postgresql://', 'postgresql+psycopg://', 1)
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

ROOMS = {}

# ========== 自定义静态文件路由（兼容大小写） ==========
@app.route('/static/cards/<name>')
def serve_card(name):
    base = os.path.join(app.static_folder, 'cards')
    for ext in ['.PNG', '.png', '.JPG', '.jpg']:
        if name.lower().endswith(('.png', '.jpg')):
            stem = name.rsplit('.', 1)[0]
            path = os.path.join(base, stem + ext)
        else:
            path = os.path.join(base, name + ext)
        if os.path.exists(path):
            return send_from_directory(base, os.path.basename(path))
    return "Not Found", 404

@app.route('/static/avatars/<name>')
def serve_avatar(name):
    base = os.path.join(app.static_folder, 'avatars')
    for ext in ['.JPG', '.jpg', '.PNG', '.png']:
        if name.lower().endswith(('.png', '.jpg')):
            stem = name.rsplit('.', 1)[0]
            path = os.path.join(base, stem + ext)
        else:
            path = os.path.join(base, name + ext)
        if os.path.exists(path):
            return send_from_directory(base, os.path.basename(path))
    return "Not Found", 404

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
                           copper=current_user.copper,
                           score=current_user.score)

# ========== 抽卡 ==========
@app.route('/draw')
@login_required
def draw_page():
    return render_template('draw.html',
                           gold=current_user.gold,
                           silver=current_user.silver,
                           copper=current_user.copper)

@app.route('/draw_card', methods=['POST'])
@login_required
def draw_card_route():
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

# ========== 收藏 ==========
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
    owned_count = len(cards_with_count)
    return render_template('collection.html',
                           cards=cards_with_count,
                           all_cards=CARDS,
                           owned_count=owned_count)

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
    owned_count = 0
    for card in CARDS:
        cid = str(card["id"])
        if cid in class_cards:
            owned_count += 1
            cards.append({**card, "owned": True,
                          "donor": class_cards[cid]["donor"],
                          "donated_at": class_cards[cid]["donated_at"]})
        else:
            cards.append({**card, "owned": False})
    return render_template('class_collection.html',
                           cards=cards,
                           owned_count=owned_count)

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

# ========== 家园 ==========
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
        result.append({"bid": bid, "name": ATTR_NAMES[bid], "attr": ATTR_CN[attr],
                       "level": level, "card": card, "deputy": dep_card,
                       "output": int(output), "max_hours": max_hours,
                       "accumulated": 0, "progress": 0})
    return render_template('buildings.html',
                           buildings=result,
                           cards=owned,
                           materials=current_user.materials,
                           total_output=int(total))

@app.route('/collect_all', methods=['POST'])
@login_required
def collect_all():
    buildings_data = current_user.get_buildings()
    building_cards = current_user.get_building_cards()
    deputies = current_user.get_deputies()
    output = total_output(buildings_data, building_cards, deputies)
    copper = int(output * 24)
    current_user.copper += copper
    current_user.silver += current_user.copper // 100
    current_user.copper = current_user.copper % 100
    current_user.gold += current_user.silver // 100
    current_user.silver = current_user.silver % 100
    current_user.last_collect = datetime.now()
    db.session.commit()
    return jsonify({"copper": copper, "silver": 0, "gold": 0})

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
    current_user.copper += copper
    current_user.silver += current_user.copper // 100
    current_user.copper = current_user.copper % 100
    current_user.gold += current_user.silver // 100
    current_user.silver = current_user.silver % 100
    db.session.commit()
    return jsonify({"copper": copper, "silver": 0, "gold": 0})

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
    coll = current_user.get_collection()
    owned = [c for c in CARDS if str(c["id"]) in coll]
    return render_template('challenge.html',
                           level=int(level),
                           cards=owned,
                           deck=[])

@app.route('/challenge/deck/save', methods=['POST'])
@login_required
def challenge_deck_save():
    return jsonify({"success": True})

@app.route('/challenge/start', methods=['POST'])
@login_required
def challenge_start():
    level = request.json.get('level', current_user.challenge_level)
    ai_cards = random.sample(CARDS, 6)
    return jsonify({"ai_cards": ai_cards, "level": level})

@app.route('/challenge/battle')
@login_required
def challenge_battle():
    return render_template('challenge_battle.html',
                           username=current_user.username,
                           nickname=current_user.nickname or current_user.username,
                           my_hand_count=6,
                           ai_hand_count=6,
                           hand=[])

@app.route('/challenge/play', methods=['POST'])
@login_required
def challenge_play():
    return jsonify({"success": True})

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
                           games=0, score=current_user.score, rank=0)

@app.route('/boka/create', methods=['POST'])
@login_required
def boka_create():
    room_id = ''.join(random.choices('ABCDEFGHJKLMNPQRSTUVWXYZ23456789', k=6))
    ROOMS[room_id] = {"owner": current_user.username, "players": [current_user.username]}
    return jsonify({"room_id": room_id})

@app.route('/boka/rooms')
@login_required
def boka_rooms():
    rooms = []
    for rid, r in ROOMS.items():
        rooms.append({
            "room_id": rid,
            "status": "准备中",
            "count": len(r["players"]),
            "owner": r["owner"],
            "players": [{"name": p, "avatar": f"/static/avatars/{p}.jpg", "is_owner": p == r["owner"]} for p in r["players"]],
            "joined": current_user.username in r["players"]
        })
    return jsonify({"rooms": rooms})

@app.route('/boka/room/<room_id>')
@login_required
def boka_room(room_id):
    return render_template('boka_room.html',
                           room_id=room_id,
                           invite_url=request.url,
                           ready_count=0,
                           player_count=1,
                           is_ready=False,
                           is_owner=True,
                           players=[{"username": current_user.username,
                                     "nickname": current_user.nickname or current_user.username,
                                     "is_owner": True, "ready": False}])

@app.route('/boka/room/<room_id>/ready', methods=['POST'])
@login_required
def boka_ready(room_id):
    return jsonify({"success": True})

@app.route('/boka/room/<room_id>/start', methods=['POST'])
@login_required
def boka_start(room_id):
    return jsonify({"success": True})

@app.route('/boka/room/<room_id>/dissolve', methods=['POST'])
@login_required
def boka_dissolve(room_id):
    ROOMS.pop(room_id, None)
    return jsonify({"success": True})

@app.route('/boka/room/<room_id>/battle')
@login_required
def boka_battle(room_id):
    return render_template('boka_battle.html',
                           room_id=room_id,
                           players=[],
                           hand=[])

@app.route('/boka/room/<room_id>/play', methods=['POST'])
@login_required
def boka_play(room_id):
    return jsonify({"success": True})

# ========== 世界 Boss ==========
@app.route('/world_boss')
@login_required
def world_boss():
    today = date.today()
    if current_user.boss_fatigue_reset != today:
        current_user.set_boss_fatigue({})
        current_user.boss_fatigue_reset = today
        db.session.commit()

    week_num = current_user.boss_week
    random.seed(week_num)
    boss = random.choice(BOSS_LIST)

    day_seed = int(today.strftime("%Y%m%d"))
    random.seed(day_seed)
    weak_attr = random.choice(list(ATTR_CN.keys()))

    hp = boss_hp(week_num)
    coll = current_user.get_collection()
    owned = [c for c in CARDS if str(c["id"]) in coll]
    fatigue = current_user.get_boss_fatigue()

    return render_template('world_boss.html',
                           boss=boss,
                           weak_attr=weak_attr,
                           weak_attr_cn=ATTR_CN[weak_attr],
                           hp=hp,
                           cards=owned,
                           fatigue=fatigue)

@app.route('/world_boss/decks')
@login_required
def world_boss_decks():
    return jsonify({"decks": []})

@app.route('/world_boss/deck/save', methods=['POST'])
@login_required
def world_boss_deck_save():
    return jsonify({"success": True})

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
    return render_template('data.html')

@app.route('/data/<mode>')
@login_required
def data_rank(mode):
    users = User.query.all()
    ranks = []
    for u in users:
        nickname = u.nickname or u.username
        if mode == 'boka':
            value = u.score
        elif mode == 'challenge':
            value = u.challenge_level - 1 if u.challenge_level > 0 else 0
        else:
            value = 0
        ranks.append({"nickname": nickname, "value": value, "games": 0, "username": u.username})
    ranks.sort(key=lambda x: x["value"], reverse=True)
    return jsonify({"ranks": ranks})

# ========== 我的资料 ==========
@app.route('/profile')
@login_required
def profile():
    trophies = current_user.get_champion_months()
    return render_template('profile.html',
                           trophies=trophies,
                           boka_best=current_user.boka_best_score,
                           boka_best_time=current_user.boka_best_time,
                           boss_best=current_user.boss_best_damage,
                           boss_best_time=current_user.boss_best_time)

# ========== 他人资料 ==========
@app.route('/user/<username>')
@login_required
def user_profile(username):
    user = User.query.filter_by(username=username).first()
    if not user:
        return "玩家不存在", 404
    trophies = user.get_champion_months()
    return render_template('user_profile.html',
                           profile_user=user,
                           trophies=trophies,
                           boka_best=user.boka_best_score,
                           boka_best_time=user.boka_best_time,
                           boss_best=user.boss_best_damage,
                           boss_best_time=user.boss_best_time)

# ========== 临时创建账号 ==========
@app.route('/init_accounts')
def init_accounts():
    ACCOUNTS = [
        ("gelu", "gelu", "格鲁"),
        ("benlei", "benlei", "奔雷"),
        ("nanju", "nanju", "楠局"),
        ("jiangzha", "jiangzha", "蒋渣"),
        ("shuanan", "shuanan", "耍男"),
        ("chenran", "chenran", "陈然"),
        ("diaonan", "diaonan", "吊男"),
        ("biesan", "biesan", "瘪三"),
        ("zhengwei", "zhengwei", "政委"),
        ("jiangmen", "jiangmen", "姜门"),
        ("xiaoxu", "xiaoxu", "小旭"),
        ("kaxiang", "kaxiang", "卡翔"),
        ("tieniu", "tieniu", "铁牛"),
        ("denghuang", "denghuang", "登黄"),
        ("tianhua", "tianhua", "天花"),
        ("haohao", "haohao", "浩浩"),
        ("lafang", "lafang", "拉芳"),
    ]
    created = []
    for username, password, nickname in ACCOUNTS:
        u = User.query.filter_by(username=username).first()
        if u:
            u.gold = 10
            u.collection = "{}"
            u.silver = 0
            u.copper = 0
            created.append(f"重置：{username}")
        else:
            u = User(username=username, nickname=nickname)
            u.set_password(password)
            u.gold = 10
            db.session.add(u)
            created.append(f"已创建：{username}")
    db.session.commit()
    return "<br>".join(created)

# ========== 启动 ==========
with app.app_context():
    db.create_all()

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=int(os.getenv('PORT', 5000)))
