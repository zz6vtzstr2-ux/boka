# app.py
import os
import random
import math
from datetime import datetime, timedelta, date
from flask import Flask, render_template, request, jsonify, redirect, url_for, send_from_directory, make_response
from flask_login import LoginManager, login_user, login_required, logout_user, current_user
from models import (
    db, User, ClassCollection,
    WorldBoss, BossDeck, BossDamage, BossBattle,
    BokaRoom, BokaPlayer,
    BokaGame, BokaGamePlayer, BokaGameRecord,
)
from cards_data import CARDS, CARD_BY_NAME, CARD_BY_ID
from combos_data import COMBOS, SPECIAL_CARDS
from game_logic import (
    draw_card, get_quality_star,
    building_output, total_output, calc_combo_stats,
    calc_score_change, challenge_materials,
    fatigue_coef, real_attr, boss_card_damage,
    boss_deck_damage, boss_deck_damage_with_bond,
    calc_bond_bonus_for_deck,
    card_with_level,
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

QUALITY_COLORS = {
    "白": "#d0d0d0", "绿": "#5cb85c", "蓝": "#4a90d9",
    "紫": "#a06cd5", "橙": "#f5a623",
}

ATTR_COLORS = {
    "lead": "#c8e0c8", "might": "#e8c8b8", "intel": "#d8c8e8",
    "politics": "#f0dcb0", "charm": "#e8b8c8",
}

BOSS_LIST = [
    {"name": "方腊", "troop": "先锋营"},
    {"name": "高俅", "troop": "中军帐"},
    {"name": "童贯", "troop": "军机处"},
    {"name": "蔡京", "troop": "粮草营"},
    {"name": "辽国元帅", "troop": "招贤馆"},
]

WEAK_ATTR_KEYS = ["lead", "might", "intel", "politics", "charm"]

BOSS_REWARD_RATIO = {
    1: 1.00, 2: 0.80, 3: 0.72, 4: 0.66, 5: 0.60,
    6: 0.55, 7: 0.50, 8: 0.46, 9: 0.42, 10: 0.38,
    11: 0.35, 12: 0.32, 13: 0.29, 14: 0.27, 15: 0.25,
    16: 0.23, 17: 0.21, 18: 0.19, 19: 0.17, 20: 0.15,
}

BOSS_FIRST_REWARD_BASE = 5.0
BOSS_FIRST_REWARD_STEP = 0.1

BOSS_BATTLE_DURATION_HOURS = 2
BOSS_DAILY_LIMIT = 2

ROOMS = {}

# ========== 收藏数据迁移辅助 ==========
def normalize_collection(coll):
    new_coll = {}
    for cid, val in coll.items():
        if isinstance(val, int):
            new_coll[cid] = {"count": val, "level": 1}
        elif isinstance(val, dict):
            new_coll[cid] = {
                "count": int(val.get("count", 0)),
                "level": max(1, min(25, int(val.get("level", 1)))),
            }
    return new_coll

def ensure_collection_migrated(user):
    if not getattr(user, "collection_migrated", False):
        coll = user.get_collection()
        new_coll = normalize_collection(coll)
        user.set_collection(new_coll)
        user.collection_migrated = True
        db.session.commit()
        return new_coll
    return user.get_collection()

def level_to_quality_star(level):
    level = max(1, min(25, level))
    quality_index = (level - 1) // 5
    star = (level - 1) % 5 + 1
    qualities = ["白", "绿", "蓝", "紫", "橙"]
    return qualities[quality_index], star

# ========== 世界 Boss 周期管理 ==========
BOSS_EPOCH_MONDAY = datetime(2026, 10, 5, 6, 0, 0)

def get_current_week_num():
    now = datetime.now()
    weekday = now.weekday()
    monday_6 = now.replace(hour=6, minute=0, second=0, microsecond=0)
    if weekday > 0 or now < monday_6:
        monday_6 = monday_6 - timedelta(days=weekday if weekday > 0 else 7)
    delta_days = (monday_6 - BOSS_EPOCH_MONDAY).days
    return max(1, delta_days // 7 + 1)

def get_current_week_start():
    now = datetime.now()
    weekday = now.weekday()
    monday_6 = now.replace(hour=6, minute=0, second=0, microsecond=0)
    if weekday > 0 or now < monday_6:
        monday_6 = monday_6 - timedelta(days=weekday if weekday > 0 else 7)
    return monday_6

def get_next_week_start():
    return get_current_week_start() + timedelta(days=7)

def generate_weak_schedule():
    base = WEAK_ATTR_KEYS[:]
    random.shuffle(base)
    extra = random.sample(WEAK_ATTR_KEYS, 2)
    week = base + extra
    random.shuffle(week)
    return week

def json_dumps_safe(obj):
    import json
    return json.dumps(obj, ensure_ascii=False)

def json_loads_safe(s):
    import json
    try:
        return json.loads(s or "[]")
    except Exception:
        return []

def ensure_world_boss():
    current_week = get_current_week_num()
    wb = WorldBoss.query.first()
    if wb is None:
        random.seed(current_week * 31)
        boss = random.choice(BOSS_LIST)
        max_hp = int((30 + (current_week - 1) * 1.2) * 10000)
        wb = WorldBoss(
            id=1, week_num=current_week,
            boss_name=boss["name"], boss_troop=boss["troop"],
            max_hp=max_hp, current_hp=max_hp,
            weak_schedule=json_dumps_safe(generate_weak_schedule()),
            started_at=datetime.now(), payout_done=False,
        )
        db.session.add(wb)
        db.session.commit()
        return wb
    if wb.week_num != current_week:
        payout_for_week(wb.week_num, wb.current_hp > 0)
        random.seed(current_week * 31)
        boss = random.choice(BOSS_LIST)
        max_hp = int((30 + (current_week - 1) * 1.2) * 10000)
        wb.week_num = current_week
        wb.boss_name = boss["name"]
        wb.boss_troop = boss["troop"]
        wb.max_hp = max_hp
        wb.current_hp = max_hp
        wb.weak_schedule = json_dumps_safe(generate_weak_schedule())
        wb.started_at = datetime.now()
        wb.killed_at = None
        wb.payout_done = False
        db.session.commit()
    return wb

def get_today_weak_attr(wb):
    schedule = json_loads_safe(wb.weak_schedule)
    if not schedule or len(schedule) < 7:
        return "might"
    idx = datetime.now().weekday()
    return schedule[idx]

def payout_for_week(week_num, killed):
    records = BossDamage.query.filter_by(week_num=week_num).all()
    if not records:
        return
    records.sort(key=lambda r: r.total_damage, reverse=True)
    first_reward = BOSS_FIRST_REWARD_BASE + (week_num - 1) * BOSS_FIRST_REWARD_STEP
    multiplier = 1.0 if killed else 0.5
    for idx, r in enumerate(records[:20], start=1):
        ratio = BOSS_REWARD_RATIO.get(idx, 0)
        if ratio <= 0:
            continue
        gold = int(first_reward * ratio * multiplier)
        user = User.query.get(r.user_id)
        if user:
            user.gold += gold
    db.session.commit()

def get_today_battle_count(user_id):
    now = datetime.now()
    today_6 = now.replace(hour=6, minute=0, second=0, microsecond=0)
    if now < today_6:
        today_6 = today_6 - timedelta(days=1)
    return BossBattle.query.filter(
        BossBattle.user_id == user_id,
        BossBattle.started_at >= today_6,
    ).count()

def get_active_battle(user_id):
    return BossBattle.query.filter_by(user_id=user_id, finished=False).first()

# ========== 静态文件路由 ==========
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
            resp = make_response(send_from_directory(base, os.path.basename(path)))
            resp.headers['Cache-Control'] = 'public, max-age=31536000'
            return resp
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
            resp = make_response(send_from_directory(base, os.path.basename(path)))
            resp.headers['Cache-Control'] = 'public, max-age=3600'
            return resp
    return "Not Found", 404

@app.route('/static/images/<name>')
def serve_image(name):
    base = os.path.join(app.static_folder, 'images')
    for ext in ['.JPG', '.jpg', '.PNG', '.png']:
        if name.lower().endswith(('.png', '.jpg')):
            stem = name.rsplit('.', 1)[0]
            path = os.path.join(base, stem + ext)
        else:
            path = os.path.join(base, name + ext)
        if os.path.exists(path):
            resp = make_response(send_from_directory(base, os.path.basename(path)))
            resp.headers['Cache-Control'] = 'public, max-age=31536000'
            return resp
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
    return render_template('draw.html')

@app.route('/draw_card', methods=['POST'])
@login_required
def draw_card_route():
    if current_user.gold < 2:
        return jsonify({"error": "金币不足"}), 400
    current_user.gold -= 2
    coll = ensure_collection_migrated(current_user)
    cards, result_type = draw_card()
    if result_type == "empty":
        db.session.commit()
        return jsonify({"type": "empty", "message": "厂商忘放卡了", "gold": current_user.gold})
    first_time = []
    for card in cards:
        cid = str(card["id"])
        if cid not in coll:
            first_time.append(card["name"])
            coll[cid] = {"count": 0, "level": 1}
        coll[cid]["count"] += 1
    current_user.set_collection(coll)
    db.session.commit()
    if result_type == "double":
        return jsonify({"type": "double", "cards": cards, "message": "双黄蛋", "first_time": first_time, "gold": current_user.gold})
    return jsonify({"type": "normal", "cards": cards, "first_time": first_time, "gold": current_user.gold})

# ========== 收藏 ==========
@app.route('/collection')
@login_required
def collection():
    coll = ensure_collection_migrated(current_user)
    cards_with_count = []
    for card in CARDS:
        cid = str(card["id"])
        entry = coll.get(cid)
        if not entry:
            continue
        count = entry["count"]
        if count <= 0:
            continue
        level = entry["level"]
        quality, star = level_to_quality_star(level)
        cards_with_count.append({
            **card, "count": count, "level": level,
            "quality": quality, "star": star,
            "quality_color": QUALITY_COLORS[quality],
            "upgrade_cost": level,
            "can_upgrade": count >= level and level < 25,
        })
    owned_count = len(cards_with_count)
    return render_template('collection.html',
                           cards=cards_with_count,
                           all_cards=CARDS,
                           owned_count=owned_count)

@app.route('/class_collection')
@login_required
def class_collection():
    records = ClassCollection.query.all()
    class_cards = {r.card_id: r for r in records}
    cards = []
    owned_count = 0
    for card in CARDS:
        cid = card["id"]
        if cid in class_cards:
            owned_count += 1
            r = class_cards[cid]
            cards.append({**card, "owned": True,
                          "donor": r.donor_username,
                          "donated_at": r.donated_at.strftime("%Y-%m-%d") if r.donated_at else ""})
        else:
            cards.append({**card, "owned": False})
    return render_template('class_collection.html',
                           cards=cards,
                           owned_count=owned_count)

@app.route('/upgrade', methods=['POST'])
@login_required
def upgrade():
    card_id = str(request.json.get('card_id'))
    coll = ensure_collection_migrated(current_user)
    if card_id not in coll:
        return jsonify({"error": "没有这张卡"}), 400
    entry = coll[card_id]
    count = entry["count"]
    level = entry["level"]
    if level >= 25:
        return jsonify({"error": "已满级"}), 400
    cost = level
    if count < cost:
        return jsonify({"error": "同名卡不足"}), 400
    entry["count"] -= cost
    entry["level"] += 1
    current_user.set_collection(coll)
    db.session.commit()
    return jsonify({"success": True, "new_count": entry["count"], "new_level": entry["level"]})

@app.route('/donate', methods=['POST'])
@login_required
def donate():
    card_id = str(request.json.get('card_id'))
    coll = ensure_collection_migrated(current_user)
    if card_id not in coll or coll[card_id]["count"] < 1:
        return jsonify({"error": "没有这张卡"}), 400
    existing = ClassCollection.query.filter_by(card_id=int(card_id)).first()
    if existing:
        return jsonify({"error": "班级已收藏此卡"}), 400
    coll[card_id]["count"] -= 1
    if coll[card_id]["count"] <= 0:
        del coll[card_id]
    current_user.set_collection(coll)
    record = ClassCollection(
        card_id=int(card_id),
        donor_username=current_user.nickname or current_user.username,
        donated_at=datetime.now()
    )
    db.session.add(record)
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
                           buildings=result, cards=owned,
                           materials=current_user.materials,
                           total_output=int(total))

@app.route('/buildings/picker/<bid>')
@login_required
def buildings_picker(bid):
    coll = current_user.get_collection()
    owned = [c for c in CARDS if str(c["id"]) in coll]
    building_cards = current_user.get_building_cards()
    deployed = {}
    for b, cid in building_cards.items():
        if cid:
            card = CARD_BY_ID.get(cid)
            if card:
                deployed[cid] = ATTR_NAMES[int(b)]
    return render_template('buildings_picker.html',
                           cards=owned, deployed=deployed, bid=int(bid))

@app.route('/buildings/set_card', methods=['POST'])
@login_required
def buildings_set_card():
    bid = str(request.json.get('bid'))
    card_id = request.json.get('card_id')
    building_cards = current_user.get_building_cards()
    for b, cid in list(building_cards.items()):
        if cid == card_id and b != bid:
            del building_cards[b]
    building_cards[bid] = card_id
    current_user.set_building_cards(building_cards)
    db.session.commit()
    return jsonify({"success": True})

@app.route('/collect_all', methods=['POST'])
@login_required
def collect_all():
    buildings_data = current_user.get_buildings()
    building_cards = current_user.get_building_cards()
    deputies = current_user.get_deputies()
    output = total_output(buildings_data, building_cards, deputies)
    copper_total = int(output * 8)
    gold = copper_total // 1000000
    silver = (copper_total % 1000000) // 10000
    copper = (copper_total % 10000) // 100
    current_user.gold += gold
    current_user.silver += silver
    current_user.copper += copper
    current_user.silver += current_user.copper // 100
    current_user.copper = current_user.copper % 100
    current_user.gold += current_user.silver // 100
    current_user.silver = current_user.silver % 100
    current_user.last_collect = datetime.now()
    db.session.commit()
    return jsonify({"gold": gold, "silver": silver, "copper": copper})

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
    copper_total = int(output * 8)
    gold = copper_total // 1000000
    silver = (copper_total % 1000000) // 10000
    copper = (copper_total % 10000) // 100
    current_user.gold += gold
    current_user.silver += silver
    current_user.copper += copper
    current_user.silver += current_user.copper // 100
    current_user.copper = current_user.copper % 100
    current_user.gold += current_user.silver // 100
    current_user.silver = current_user.silver % 100
    db.session.commit()
    return jsonify({"gold": gold, "silver": silver, "copper": copper})

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

# ========== 挑战（占位，下一步做） ==========
@app.route('/challenge')
@login_required
def challenge():
    level = request.args.get('level', current_user.challenge_level)
    coll = current_user.get_collection()
    owned = [c for c in CARDS if str(c["id"]) in coll]
    return render_template('challenge.html', level=int(level), cards=owned, deck=[])

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
                           my_hand_count=6, ai_hand_count=6, hand=[])

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
def gen_room_code():
    chars = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    for _ in range(50):
        code = ''.join(random.choices(chars, k=6))
        if not BokaRoom.query.filter_by(room_code=code).first():
            return code
    return ''.join(random.choices(chars, k=6))

@app.route('/boka/reset_all')
@login_required
def boka_reset_all():
    BokaGamePlayer.query.delete()
    BokaGame.query.delete()
    BokaPlayer.query.delete()
    BokaRoom.query.delete()
    User.query.update({"boka_room_id": None})
    db.session.commit()
    return "✅ 搏卡房间数据已全部清空"

@app.route('/boka')
@login_required
def boka():
    all_users = User.query.order_by(User.score.desc()).all()
    my_rank = 0
    for idx, u in enumerate(all_users, start=1):
        if u.id == current_user.id:
            my_rank = idx
            break
    return render_template('boka.html', games=0, score=current_user.score, rank=my_rank)

@app.route('/boka/create', methods=['POST'])
@login_required
def boka_create():
    leave_any_room(current_user)
    code = gen_room_code()
    room = BokaRoom(
        room_code=code, owner_username=current_user.username,
        status="waiting", max_players=14, created_at=datetime.now(),
    )
    db.session.add(room)
    db.session.flush()
    p = BokaPlayer(
        room_id=room.id, username=current_user.username,
        nickname=current_user.nickname or current_user.username,
        ready=False, seat=0, joined_at=datetime.now(),
    )
    db.session.add(p)
    current_user.boka_room_id = room.id
    db.session.commit()
    return jsonify({"room_id": code})

@app.route('/boka/rooms')
@login_required
def boka_rooms():
    rooms = BokaRoom.query.filter_by(status="waiting").order_by(BokaRoom.created_at.desc()).all()
    result = []
    for r in rooms:
        players = BokaPlayer.query.filter_by(room_id=r.id).all()
        result.append({
            "room_id": r.room_code, "status": "准备中",
            "count": len(players), "owner": r.owner_username,
            "players": [
                {"name": p.nickname or p.username, "username": p.username,
                 "avatar": f"/static/avatars/{p.username}.jpg",
                 "is_owner": p.username == r.owner_username}
                for p in players
            ],
            "joined": any(p.username == current_user.username for p in players),
        })
    return jsonify({"rooms": result})

def leave_any_room(user):
    if not user.boka_room_id:
        return
    room = BokaRoom.query.get(user.boka_room_id)
    if room:
        if room.owner_username == user.username:
            BokaPlayer.query.filter_by(room_id=room.id).delete()
            db.session.delete(room)
        else:
            BokaPlayer.query.filter_by(room_id=room.id, username=user.username).delete()
    user.boka_room_id = None
    db.session.commit()

@app.route('/boka/room/<room_code>')
@login_required
def boka_room(room_code):
    room = BokaRoom.query.filter_by(room_code=room_code).first()
    if not room:
        return redirect(url_for('boka'))
    me = BokaPlayer.query.filter_by(room_id=room.id, username=current_user.username).first()
    if not me:
        if current_user.boka_room_id and current_user.boka_room_id != room.id:
            leave_any_room(current_user)
            room = BokaRoom.query.filter_by(room_code=room_code).first()
            if not room:
                return redirect(url_for('boka'))
            me = BokaPlayer.query.filter_by(room_id=room.id, username=current_user.username).first()
        if not me:
            player_count = BokaPlayer.query.filter_by(room_id=room.id).count()
            if player_count >= room.max_players:
                return "房间已满", 403
            me = BokaPlayer(
                room_id=room.id, username=current_user.username,
                nickname=current_user.nickname or current_user.username,
                ready=False, seat=player_count, joined_at=datetime.now(),
            )
            db.session.add(me)
            current_user.boka_room_id = room.id
            db.session.commit()
    if room.status == "playing":
        return redirect(url_for('boka_battle', room_code=room_code))
    players = BokaPlayer.query.filter_by(room_id=room.id).order_by(BokaPlayer.seat).all()
    ready_count = sum(1 for p in players if p.ready)
    is_owner = room.owner_username == current_user.username
    is_ready = me.ready
    if me.is_temporary_away:
        me.is_temporary_away = False
        db.session.commit()
    return render_template('boka_room.html',
                           room_code=room.room_code, room_id=room.id,
                           invite_url=request.url,
                           ready_count=ready_count, player_count=len(players),
                           is_ready=is_ready, is_owner=is_owner,
                           players=[
                               {"username": p.username, "nickname": p.nickname or p.username,
                                "is_owner": p.username == room.owner_username,
                                "ready": p.ready, "is_away": p.is_temporary_away}
                               for p in players
                           ])

@app.route('/boka/room/<room_code>/state')
@login_required
def boka_room_state(room_code):
    room = BokaRoom.query.filter_by(room_code=room_code).first()
    if not room:
        return jsonify({"error": "房间不存在"}), 404
    players = BokaPlayer.query.filter_by(room_id=room.id).order_by(BokaPlayer.seat).all()
    return jsonify({
        "status": room.status,
        "ready_count": sum(1 for p in players if p.ready),
        "player_count": len(players),
        "owner": room.owner_username,
        "players": [
            {"username": p.username, "nickname": p.nickname or p.username,
             "is_owner": p.username == room.owner_username,
             "ready": p.ready, "is_away": p.is_temporary_away}
            for p in players
        ],
    })

@app.route('/boka/room/<room_code>/ready', methods=['POST'])
@login_required
def boka_ready(room_code):
    room = BokaRoom.query.filter_by(room_code=room_code).first()
    if not room:
        return jsonify({"error": "房间不存在"}), 404
    me = BokaPlayer.query.filter_by(room_id=room.id, username=current_user.username).first()
    if not me:
        return jsonify({"error": "你不在房间"}), 400
    me.ready = not me.ready
    db.session.commit()
    return jsonify({"success": True, "ready": me.ready})

@app.route('/boka/room/<room_code>/start', methods=['POST'])
@login_required
def boka_start(room_code):
    room = BokaRoom.query.filter_by(room_code=room_code).first()
    if not room:
        return jsonify({"error": "房间不存在"}), 404
    if room.owner_username != current_user.username:
        return jsonify({"error": "只有房主能开始"}), 403
    players = BokaPlayer.query.filter_by(room_id=room.id).order_by(BokaPlayer.seat).all()
    if len(players) < 2:
        return jsonify({"error": "至少需要 2 名玩家"}), 400
    if not all(p.ready for p in players):
        return jsonify({"error": "还有玩家未准备"}), 400

    class_records = ClassCollection.query.all()
    n_players = len(players)
    min_cards = n_players * 3
    if len(class_records) < min_cards:
        return jsonify({"error": f"班级收藏册只有 {len(class_records)} 张，{n_players} 人至少需要 {min_cards} 张"}), 400
    class_card_ids = [r.card_id for r in class_records]

    PRIORITY_EXTRA = ["扈三娘", "凌振", "陶宗旺", "樊瑞", "白胜", "孙二娘"]
    priority_ids = []
    for c in CARDS:
        if c["id"] <= 36 or c["name"] in PRIORITY_EXTRA:
            priority_ids.append(c["id"])
    available_priority = [cid for cid in priority_ids if cid in class_card_ids]
    available_rest = [cid for cid in class_card_ids if cid not in priority_ids]
    random.shuffle(available_priority)
    random.shuffle(available_rest)
    pool = available_priority[:42]
    if len(pool) < 42:
        need = 42 - len(pool)
        pool += available_rest[:need]
    if len(pool) < len(players):
        return jsonify({"error": f"卡池只有 {len(pool)} 张，不够 {len(players)} 人分"}), 400

    game = BokaGame(
        room_id=room.id, round_no=0, phase="waiting",
        card_pool=json_dumps_safe(pool),
        history=json_dumps_safe([]),
        created_at=datetime.now(),
        beauty_left=3,
    )
    db.session.add(game)
    db.session.flush()

    n = len(players)
    cards_per_player = min(6, len(pool) // n)
    random.shuffle(pool)
    for i, p in enumerate(players):
        start = i * cards_per_player
        end = start + cards_per_player
        hand = pool[start:end]
        gp = BokaGamePlayer(
            game_id=game.id, username=p.username,
            nickname=p.nickname or p.username,
            hand=json_dumps_safe(hand),
            ready_card=json_dumps_safe([]), locked=False,
        )
        db.session.add(gp)
    remaining_pool = pool[cards_per_player * n:]
    game.card_pool = json_dumps_safe(remaining_pool)
    room.status = "playing"
    room.started_at = datetime.now()
    game.round_no = 1
    game.phase = "selecting"
    db.session.commit()
    return jsonify({"success": True})

@app.route('/boka/room/<room_code>/dissolve', methods=['POST'])
@login_required
def boka_dissolve(room_code):
    room = BokaRoom.query.filter_by(room_code=room_code).first()
    if not room:
        return jsonify({"error": "房间不存在"}), 404
    if room.owner_username != current_user.username:
        return jsonify({"error": "只有房主能解散"}), 403
    players = BokaPlayer.query.filter_by(room_id=room.id).all()
    for p in players:
        u = User.query.filter_by(username=p.username).first()
        if u:
            u.boka_room_id = None
    BokaPlayer.query.filter_by(room_id=room.id).delete()
    db.session.delete(room)
    db.session.commit()
    return jsonify({"success": True})

@app.route('/boka/room/<room_code>/leave', methods=['POST'])
@login_required
def boka_leave(room_code):
    room = BokaRoom.query.filter_by(room_code=room_code).first()
    if not room:
        return jsonify({"error": "房间不存在"}), 404
    me = BokaPlayer.query.filter_by(room_id=room.id, username=current_user.username).first()
    if not me:
        return jsonify({"error": "你不在房间"}), 400
    me.is_temporary_away = True
    me.ready = False
    db.session.commit()
    return jsonify({"success": True})

@app.route('/boka/room/<room_code>/quit', methods=['POST'])
@login_required
def boka_quit(room_code):
    room = BokaRoom.query.filter_by(room_code=room_code).first()
    if not room:
        return jsonify({"error": "房间不存在"}), 404
    if room.owner_username == current_user.username:
        players = BokaPlayer.query.filter_by(room_id=room.id).all()
        for p in players:
            u = User.query.filter_by(username=p.username).first()
            if u:
                u.boka_room_id = None
        BokaPlayer.query.filter_by(room_id=room.id).delete()
        db.session.delete(room)
    else:
        BokaPlayer.query.filter_by(room_id=room.id, username=current_user.username).delete()
        current_user.boka_room_id = None
    db.session.commit()
    return jsonify({"success": True})

@app.route('/boka/room/<room_code>/battle')
@login_required
def boka_battle(room_code):
    room = BokaRoom.query.filter_by(room_code=room_code).first()
    if not room:
        return redirect(url_for('boka'))
    game = BokaGame.query.filter_by(room_id=room.id).order_by(BokaGame.id.desc()).first()
    if not game:
        return redirect(url_for('boka_room', room_code=room_code))
    gps = BokaGamePlayer.query.filter_by(game_id=game.id).all()
    layout = calc_boka_layout(len(gps), current_user.username, gps)
    me = next((g for g in gps if g.username == current_user.username), None)
    my_hand_ids = json_loads_safe(me.hand) if me else []
    my_hand = [CARD_BY_ID.get(cid) for cid in my_hand_ids if CARD_BY_ID.get(cid)]
    players_view = []
    for g in gps:
        players_view.append({
            "username": g.username, "nickname": g.nickname,
            "is_me": g.username == current_user.username,
            "hand_count": len(json_loads_safe(g.hand)),
            "locked": g.locked,
        })
    round_phase = "比攻" if game.round_no % 2 == 1 else "比防"
    return render_template('boka_battle.html',
                           room_code=room_code, room_id=room.id, game_id=game.id,
                           round_no=game.round_no, round_phase=round_phase,
                           phase=game.phase, players=players_view,
                           layout=layout, hand=my_hand,
                           my_ready=json_loads_safe(me.ready_card) if me else [])

@app.route('/boka/room/<room_code>/validate_combo', methods=['POST'])
@login_required
def boka_validate_combo(room_code):
    room = BokaRoom.query.filter_by(room_code=room_code).first()
    if not room:
        return jsonify({"error": "房间不存在"}), 404
    card_ids = request.json.get('card_ids', [])
    if not isinstance(card_ids, list):
        return jsonify({"error": "参数错误"}), 400
    if len(card_ids) == 0:
        return jsonify({"valid": False, "reason": "至少出 1 张"})
    cards = [CARD_BY_ID.get(cid) for cid in card_ids if CARD_BY_ID.get(cid)]
    if len(cards) != len(card_ids):
        return jsonify({"valid": False, "reason": "卡不存在"})
    if len(cards) == 1:
        return jsonify({"valid": True, "type": "single"})
    atk, dfn, combo_name = calc_combo_stats(cards)
    if atk is None:
        return jsonify({"valid": False, "reason": "不是有效组合"})
    return jsonify({"valid": True, "type": "combo", "name": combo_name, "atk": atk, "def": dfn})

@app.route('/boka/room/<room_code>/play', methods=['POST'])
@login_required
def boka_play(room_code):
    room = BokaRoom.query.filter_by(room_code=room_code).first()
    if not room:
        return jsonify({"error": "房间不存在"}), 404
    game = BokaGame.query.filter_by(room_id=room.id).order_by(BokaGame.id.desc()).first()
    if not game or game.phase not in ("selecting",):
        return jsonify({"error": "当前不可出牌"}), 400
    me = BokaGamePlayer.query.filter_by(game_id=game.id, username=current_user.username).first()
    if not me:
        return jsonify({"error": "你不在本局"}), 403
    if me.locked:
        return jsonify({"error": "你已经锁定"}), 400
    card_ids = request.json.get('card_ids', [])
    if not isinstance(card_ids, list) or len(card_ids) < 1:
        return jsonify({"error": "至少出 1 张"}), 400
    my_hand = json_loads_safe(me.hand)
    for cid in card_ids:
        if cid not in my_hand:
            return jsonify({"error": f"卡 {cid} 不在手牌"}), 400
    me.ready_card = json_dumps_safe(card_ids)
    me.locked = True
    db.session.commit()
    all_players = BokaGamePlayer.query.filter_by(game_id=game.id).all()
    if all(p.locked for p in all_players):
        resolve_boka_round(game)
    return jsonify({"success": True})

@app.route('/boka/room/<room_code>/battle_state')
@login_required
def boka_battle_state(room_code):
    room = BokaRoom.query.filter_by(room_code=room_code).first()
    if not room:
        return jsonify({"error": "房间不存在"}), 404
    game = BokaGame.query.filter_by(room_id=room.id).order_by(BokaGame.id.desc()).first()
    if not game:
        return jsonify({"error": "无对局"}), 404

    if game.phase == "revealing" and game.revealed_at:
        elapsed = (datetime.now() - game.revealed_at).total_seconds()
        if elapsed >= 3.0:
            gps_check = BokaGamePlayer.query.filter_by(game_id=game.id).all()
            alive = [g for g in gps_check if len(json_loads_safe(g.hand)) > 0 and not g.surrendered]
            if len(alive) <= 1 and game.phase != "finished":
                finish_boka_game(game, alive)
            else:
                game.round_no += 1
                game.phase = "selecting"
                game.revealed_at = None
                game.round_winner_card_id = None
                game.winner_card_id = None
                game.winner_username = None
                db.session.commit()

    gps = BokaGamePlayer.query.filter_by(game_id=game.id).all()
    me = next((g for g in gps if g.username == current_user.username), None)
    all_locked = all(g.locked for g in gps)

    players_view = []
    for g in gps:
        ready_cards = json_loads_safe(g.ready_card)
        show_cards = (game.phase in ("revealing", "finished")) or (g.username == current_user.username)
        players_view.append({
            "username": g.username, "nickname": g.nickname,
            "is_me": g.username == current_user.username,
            "hand_count": len(json_loads_safe(g.hand)),
            "locked": g.locked,
            "ready_cards": [CARD_BY_ID.get(cid) for cid in (ready_cards if show_cards else []) if CARD_BY_ID.get(cid)],
            "rank": g.rank, "score_change": g.score_change or 0,
            "surrendered": g.surrendered,
        })

    my_hand_ids = json_loads_safe(me.hand) if me else []
    my_ready_ids = json_loads_safe(me.ready_card) if me else []

    return jsonify({
        "round_no": game.round_no, "phase": game.phase,
        "round_phase": "比攻" if game.round_no % 2 == 1 else "比防",
        "all_locked": all_locked,
        "my_hand": [CARD_BY_ID.get(cid) for cid in my_hand_ids if CARD_BY_ID.get(cid)],
        "my_ready": [CARD_BY_ID.get(cid) for cid in my_ready_ids if CARD_BY_ID.get(cid)],
        "players": players_view,
        "winner_card_id": game.round_winner_card_id,
        "winner_username": game.winner_username,
        "pool_count": len(json_loads_safe(game.card_pool)),
        "history": json_loads_safe(game.history),
        "finished": game.phase == "finished",
        "beauty_left": game.beauty_left if game.beauty_left is not None else 3,
    })

# ========== 搏卡战斗核心 ==========
HANDSOME_NAMES = {"林冲", "柴进", "燕青", "花荣", "徐宁"}
BOMB_NAMES = {"白胜", "孙二娘"}
BEAUTY_NAME = "扈三娘"
SONGJIANG_NAME = "宋江"

def _is_combo_with_special(cards, special_tag):
    """判断 cards 是否是带某个 special 的组合"""
    if len(cards) < 2:
        return False
    atk, dfn, combo_name = calc_combo_stats(cards)
    if combo_name is None:
        return False
    for combo in COMBOS:
        if combo["name"] == combo_name and combo.get("special") == special_tag:
            return True
    return False

def resolve_boka_round(game):
    """
    一轮结算。
    优先级：五虎将/八虎骑 → 风流威猛 → 水军三兄弟 → 炸弹 → 美女 → 普通
    """
    gps = BokaGamePlayer.query.filter_by(game_id=game.id).all()
    is_atk_round = (game.round_no % 2 == 1)
    dim = "atk" if is_atk_round else "def"
    other_dim = "def" if is_atk_round else "atk"

    # 收集所有出战卡
    played = []  # [{"username": ..., "cards": [...], "value":..., "other":..., "is_combo":..., "combo_name":...}]
    for g in gps:
        card_ids = json_loads_safe(g.ready_card)
        if not card_ids:
            continue
        cards_raw = []
        for cid in card_ids:
            base = CARD_BY_ID.get(cid)
            if not base:
                continue
            # 附加等级
            level = 1
            coll = User.query.filter_by(username=g.username).first()
            if coll:
                user_coll = coll.get_collection() if hasattr(coll, "get_collection") else {}
                entry = user_coll.get(str(cid))
                if entry:
                    level = entry.get("level", 1)
            card = dict(base)
            card["level"] = level
            cards_raw.append(card)
        if not cards_raw:
            continue
        atk, dfn, combo_name = calc_combo_stats(cards_raw) if len(cards_raw) > 1 else (None, None, None)
        if len(cards_raw) == 1:
            a, d = card_with_level(cards_raw[0], cards_raw[0]["level"])
            value = a if is_atk_round else d
            other = d if is_atk_round else a
            is_combo = False
        else:
            if atk is None:
                # 非法组合，按普通处理
                continue
            value = atk if is_atk_round else dfn
            other = dfn if is_atk_round else atk
            is_combo = True
        played.append({
            "username": g.username,
            "cards": cards_raw,
            "card_ids": card_ids,
            "value": value,
            "other": other,
            "is_combo": is_combo,
            "combo_name": combo_name,
        })

    if not played:
        game.revealed_at = datetime.now()
        game.phase = "revealing"
        db.session.commit()
        return

    pool = json_loads_safe(game.card_pool)
    round_record = {"round": game.round_no, "dim": dim, "played": []}

    # ====== 1. 五虎将 / 八虎骑 ======
    def has_combo_tag(tag):
        for p in played:
            if not p["is_combo"]:
                continue
            for combo in COMBOS:
                if combo["name"] == p["combo_name"] and combo.get("special") == tag:
                    return p
        return None

    top_combo = has_combo_tag("bomb_eater_steal1")
    if top_combo:
        _resolve_top_combo(game, gps, played, top_combo, pool, round_record, dim, other_dim)
        _finalize_round(game, gps, pool, round_record)
        return

    # ====== 2. 风流威猛 / 水军三兄弟 ======
    eat_combo = has_combo_tag("bomb_eater")
    if eat_combo:
        _resolve_eat_combo(game, gps, played, eat_combo, pool, round_record, dim, other_dim)
        _finalize_round(game, gps, pool, round_record)
        return

    # ====== 3. 炸弹 ======
    has_bomb = any(c["name"] in BOMB_NAMES for p in played for c in p["cards"])
    if has_bomb:
        for p in played:
            pool.extend(p["card_ids"])
            g = next(x for x in gps if x.username == p["username"])
            hand = json_loads_safe(g.hand)
            hand = [cid for cid in hand if cid not in p["card_ids"]]
            g.hand = json_dumps_safe(hand)
            g.ready_card = json_dumps_safe([])
            g.locked = False
            round_record["played"].append({
                "username": p["username"],
                "cards": [{"id": c["id"], "name": c["name"], "atk": c["atk"], "def": c["def"]} for c in p["cards"]],
                "value": p["value"], "result": "bombed",
            })
        game.round_winner_card_id = None
        game.winner_username = None
        _finalize_round(game, gps, pool, round_record)
        return

    # ====== 4. 美女 ======
    beauty_p = None
    for p in played:
        for c in p["cards"]:
            if c["name"] == BEAUTY_NAME:
                beauty_p = p
                break
        if beauty_p:
            break

    if beauty_p:
        # 美女出场
        beauty_left = game.beauty_left if game.beauty_left is not None else 3
        # 找帅哥
        handsome_players = []
        for p in played:
            for c in p["cards"]:
                if c["name"] in HANDSOME_NAMES:
                    handsome_players.append(p)
                    break

        # 计算"剩余卡"（除美女、所有帅哥外）
        handsome_card_ids = set()
        for hp in handsome_players:
            for c in hp["cards"]:
                if c["name"] in HANDSOME_NAMES:
                    handsome_card_ids.add(c["id"])
        beauty_card_ids = {c["id"] for c in beauty_p["cards"] if c["name"] == BEAUTY_NAME}

        remaining_card_ids = []
        for p in played:
            for c in p["cards"]:
                if c["id"] in beauty_card_ids:
                    continue
                if c["id"] in handsome_card_ids:
                    continue
                remaining_card_ids.append(c["id"])

        beauty_owner_name = beauty_p["username"]
        beauty_owner_g = next(x for x in gps if x.username == beauty_owner_name)

        # 剩余卡进美女打出者手牌
        beauty_owner_hand = json_loads_safe(beauty_owner_g.hand)
        beauty_owner_hand.extend(remaining_card_ids)

        # 所有人打出的卡从手牌里移除（后面再加回）
        for p in played:
            g = next(x for x in gps if x.username == p["username"])
            hand = json_loads_safe(g.hand)
            hand = [cid for cid in hand if cid not in p["card_ids"]]
            g.hand = json_dumps_safe(hand)

        if beauty_left >= 2:
            # 前 2 次：有帅哥 / 无帅哥
            if handsome_players:
                # 攻/防最高的帅哥
                best_hp = max(handsome_players, key=lambda x: (x["value"], x["other"]))
                best_hp_g = next(x for x in gps if x.username == best_hp["username"])
                best_hand = json_loads_safe(best_hp_g.hand)
                best_hand.append(beauty_card_ids.pop() if beauty_card_ids else next(iter(beauty_card_ids)))
                # 上面这句有问题，改为直接 append 美女卡
                best_hp_g.hand = json_dumps_safe(best_hand)
                # 所有帅哥进卡袋
                for hp in handsome_players:
                    for c in hp["cards"]:
                        if c["name"] in HANDSOME_NAMES:
                            pool.append(c["id"])
                # 美女进 best_hp 手牌
                beauty_id = list(beauty_card_ids)[0] if beauty_card_ids else None
                if beauty_id is not None:
                    best_hand2 = json_loads_safe(best_hp_g.hand)
                    if beauty_id not in best_hand2:
                        best_hand2.append(beauty_id)
                    best_hp_g.hand = json_dumps_safe(best_hand2)
            else:
                # 无帅哥：本轮最大进美女
                best = max(played, key=lambda x: (x["value"], x["other"]))
                best_g = next(x for x in gps if x.username == best["username"])
                best_hand = json_loads_safe(best_g.hand)
                for c in beauty_p["cards"]:
                    if c["name"] == BEAUTY_NAME and c["id"] not in best_hand:
                        best_hand.append(c["id"])
                best_g.hand = json_dumps_safe(best_hand)
                # 吴用 + 美女：吴用进卡袋
                for c in beauty_p["cards"]:
                    if c["name"] == "吴用":
                        pool.append(c["id"])

            game.beauty_left = beauty_left - 1
        else:
            # 最后一次：美女进卡袋
            for c in beauty_p["cards"]:
                pool.append(c["id"])
            if handsome_players:
                for hp in handsome_players:
                    for c in hp["cards"]:
                        if c["name"] in HANDSOME_NAMES:
                            pool.append(c["id"])
            game.beauty_left = 0

        # 剩余卡加回美女打出者手牌
        beauty_owner_hand2 = json_loads_safe(beauty_owner_g.hand)
        beauty_owner_hand2.extend(remaining_card_ids)
        beauty_owner_g.hand = json_dumps_safe(beauty_owner_hand2)

        # 清理其他玩家
        for p in played:
            g = next(x for x in gps if x.username == p["username"])
            if g.username == beauty_owner_name:
                continue
            g.ready_card = json_dumps_safe([])
            g.locked = False

        # 美女打出者清理备战区
        beauty_owner_g.ready_card = json_dumps_safe([])
        beauty_owner_g.locked = False

        game.round_winner_card_id = beauty_card_ids and list(beauty_card_ids)[0] or None
        game.winner_username = beauty_owner_name

        for p in played:
            round_record["played"].append({
                "username": p["username"],
                "cards": [{"id": c["id"], "name": c["name"], "atk": c["atk"], "def": c["def"]} for c in p["cards"]],
                "value": p["value"], "result": "beauty",
            })

        _finalize_round(game, gps, pool, round_record)
        return

    # ====== 5. 普通比大小 ======
    best = max(played, key=lambda x: (x["value"], x["other"]))
    winners = [p for p in played if p["value"] == best["value"] and p["other"] == best["other"]]
    winner = random.choice(winners) if len(winners) > 1 else winners[0]
    winner_name = winner["username"]

    # 所有人打出的卡先从手牌移除
    for p in played:
        g = next(x for x in gps if x.username == p["username"])
        hand = json_loads_safe(g.hand)
        hand = [cid for cid in hand if cid not in p["card_ids"]]
        g.hand = json_dumps_safe(hand)

    # 赢家打出的全部卡 → 进卡袋
    for cid in winner["card_ids"]:
        pool.append(cid)

    # 输家打出的卡 → 进赢家手牌
    winner_g = next(x for x in gps if x.username == winner_name)
    winner_hand = json_loads_safe(winner_g.hand)
    for p in played:
        if p["username"] == winner_name:
            continue
        winner_hand.extend(p["card_ids"])

    # 若赢家组合是 bomb_eater_steal1（五虎将/八虎骑），再偷 1 张
    if winner["is_combo"] and winner["combo_name"]:
        for combo in COMBOS:
            if combo["name"] == winner["combo_name"] and combo.get("special") == "bomb_eater_steal1":
                for p in played:
                    if p["username"] == winner_name:
                        continue
                    loser_g = next(x for x in gps if x.username == p["username"])
                    loser_hand = json_loads_safe(loser_g.hand)
                    if loser_hand:
                        stolen = random.choice(loser_hand)
                        loser_hand.remove(stolen)
                        winner_hand.append(stolen)
                        loser_g.hand = json_dumps_safe(loser_hand)
                break

    winner_g.hand = json_dumps_safe(winner_hand)

    for p in played:
        g = next(x for x in gps if x.username == p["username"])
        g.ready_card = json_dumps_safe([])
        g.locked = False
        round_record["played"].append({
            "username": p["username"],
            "cards": [{"id": c["id"], "name": c["name"], "atk": c["atk"], "def": c["def"]} for c in p["cards"]],
            "value": p["value"],
            "result": "win" if p["username"] == winner_name else "lose",
        })

    max_card_id = max(
        winner["card_ids"],
        key=lambda cid: (CARD_BY_ID.get(cid, {}).get(dim, 0), CARD_BY_ID.get(cid, {}).get(other_dim, 0))
    )
    game.round_winner_card_id = max_card_id
    game.winner_username = winner_name

    _finalize_round(game, gps, pool, round_record)


def _resolve_top_combo(game, gps, played, combo_p, pool, round_record, dim, other_dim):
    """五虎将 / 八虎骑：吃一切 + 抽卡"""
    winner_name = combo_p["username"]
    # 所有人打出的卡从手牌移除
    for p in played:
        g = next(x for x in gps if x.username == p["username"])
        hand = json_loads_safe(g.hand)
        hand = [cid for cid in hand if cid not in p["card_ids"]]
        g.hand = json_dumps_safe(hand)
    # 组合卡进卡袋
    for cid in combo_p["card_ids"]:
        pool.append(cid)
    # 输家的卡 → 进赢家手牌 + 每输家偷 1 张
    winner_g = next(x for x in gps if x.username == winner_name)
    winner_hand = json_loads_safe(winner_g.hand)
    for p in played:
        if p["username"] == winner_name:
            continue
        winner_hand.extend(p["card_ids"])
        loser_g = next(x for x in gps if x.username == p["username"])
        loser_hand = json_loads_safe(loser_g.hand)
        if loser_hand:
            stolen = random.choice(loser_hand)
            loser_hand.remove(stolen)
            winner_hand.append(stolen)
            loser_g.hand = json_dumps_safe(loser_hand)
    winner_g.hand = json_dumps_safe(winner_hand)

    for p in played:
        g = next(x for x in gps if x.username == p["username"])
        g.ready_card = json_dumps_safe([])
        g.locked = False
        round_record["played"].append({
            "username": p["username"],
            "cards": [{"id": c["id"], "name": c["name"], "atk": c["atk"], "def": c["def"]} for c in p["cards"]],
            "value": p["value"],
            "result": "win" if p["username"] == winner_name else "lose",
        })
    max_card_id = combo_p["card_ids"][0] if combo_p["card_ids"] else None
    game.round_winner_card_id = max_card_id
    game.winner_username = winner_name


def _resolve_eat_combo(game, gps, played, combo_p, pool, round_record, dim, other_dim):
    """风流威猛 / 水军三兄弟：吃炸弹和美女，正常比大小"""
    winner_name = combo_p["username"]
    for p in played:
        g = next(x for x in gps if x.username == p["username"])
        hand = json_loads_safe(g.hand)
        hand = [cid for cid in hand if cid not in p["card_ids"]]
        g.hand = json_dumps_safe(hand)
    for cid in combo_p["card_ids"]:
        pool.append(cid)
    winner_g = next(x for x in gps if x.username == winner_name)
    winner_hand = json_loads_safe(winner_g.hand)
    for p in played:
        if p["username"] == winner_name:
            continue
        winner_hand.extend(p["card_ids"])
    winner_g.hand = json_dumps_safe(winner_hand)

    for p in played:
        g = next(x for x in gps if x.username == p["username"])
        g.ready_card = json_dumps_safe([])
        g.locked = False
        round_record["played"].append({
            "username": p["username"],
            "cards": [{"id": c["id"], "name": c["name"], "atk": c["atk"], "def": c["def"]} for c in p["cards"]],
            "value": p["value"],
            "result": "win" if p["username"] == winner_name else "lose",
        })
    max_card_id = combo_p["card_ids"][0] if combo_p["card_ids"] else None
    game.round_winner_card_id = max_card_id
    game.winner_username = winner_name


def _finalize_round(game, gps, pool, round_record):
    """结算完毕后，检查出完手牌、游戏结束、切阶段"""
    for g in gps:
        hand = json_loads_safe(g.hand)
        if len(hand) == 0 and g.finished_order is None and not g.surrendered:
            max_order = db.session.query(db.func.max(BokaGamePlayer.finished_order)).filter_by(game_id=game.id).scalar() or 0
            g.finished_order = max_order + 1

    alive = [g for g in gps if len(json_loads_safe(g.hand)) > 0 and not g.surrendered]
    game.card_pool = json_dumps_safe(pool)
    history = json_loads_safe(game.history)
    history.append(round_record)
    game.history = json_dumps_safe(history)

    if len(alive) <= 1:
        finish_boka_game(game, alive)
    else:
        game.phase = "revealing"
        game.revealed_at = datetime.now()
    db.session.commit()


def finish_boka_game(game, alive):
    gps = BokaGamePlayer.query.filter_by(game_id=game.id).all()
    survivors = [g for g in gps if g.username in [a.username for a in alive]]
    finished = [g for g in gps if g.finished_order is not None]
    surrendered = [g for g in gps if g.surrendered]
    finished.sort(key=lambda g: g.finished_order, reverse=True)
    rank_order = []
    for s in survivors:
        rank_order.append(s)
    for f in finished:
        rank_order.append(f)
    for s in surrendered:
        if s not in rank_order:
            rank_order.append(s)
    n = len(rank_order)
    all_scores = [User.query.filter_by(username=g.username).first().score or 0 for g in rank_order]
    avg_score = sum(all_scores) / n if n else 0
    for idx, g in enumerate(rank_order, start=1):
        g.rank = idx
    for g in rank_order:
        u = User.query.filter_by(username=g.username).first()
        if not u:
            continue
        old_score = u.score or 0
        change = calc_boka_score_change(old_score, g.rank, n, avg_score)
        new_score = old_score + change
        if u.max_score is None:
            u.max_score = 0
        floor = (u.max_score // 1000) * 1000
        if new_score < floor:
            new_score = floor
        if new_score < 0:
            new_score = 0
        if new_score > u.max_score:
            u.max_score = new_score
        g.score_change = new_score - old_score
        u.score = new_score
        rec = BokaGameRecord(
            username=g.username, game_id=game.id, room_code=None,
            rank=g.rank, player_count=n,
            score_before=old_score, score_change=g.score_change,
            score_after=new_score, played_at=datetime.now(),
        )
        db.session.add(rec)
    game.phase = "finished"
    game.finished_at = datetime.now()
    room = BokaRoom.query.get(game.room_id)
    if room:
        room.status = "waiting"
        BokaPlayer.query.filter_by(room_id=room.id).update({"ready": False})
    db.session.commit()


def calc_boka_score_change(my_score, rank, total_players, avg_score):
    base_table = {
        2:  [25, -25],
        3:  [45, 15, -45],
        4:  [60, 15, -15, -60],
        5:  [75, 30, 0, -30, -75],
        6:  [85, 40, 10, -10, -40, -85],
        7:  [95, 50, 20, 0, -20, -50, -95],
        8:  [100, 60, 30, 10, -10, -30, -60, -100],
        9:  [105, 65, 35, 15, -5, -15, -35, -65, -105],
        10: [110, 70, 40, 20, 0, -20, -40, -70, -90, -110],
        11: [115, 75, 45, 25, 5, -5, -25, -45, -75, -95, -115],
        12: [120, 80, 50, 30, 10, 0, -10, -30, -50, -80, -100, -120],
        13: [125, 85, 55, 35, 15, 5, -5, -15, -35, -55, -85, -105, -125],
        14: [130, 90, 60, 40, 20, 10, 0, -10, -20, -40, -60, -90, -110, -130],
    }
    n = max(2, min(14, total_players))
    row = base_table.get(n, base_table[14])
    if rank < 1:
        rank = 1
    if rank > n:
        rank = n
    base = row[rank - 1]
    coef = 1 + 0.5 * math.log((avg_score + 1000) / (my_score + 1000))
    coef = max(0.5, min(3.0, coef))
    if base >= 0:
        return int(base * coef)
    else:
        return -int(-base / coef)

@app.route('/boka/room/<room_code>/surrender', methods=['POST'])
@login_required
def boka_surrender(room_code):
    room = BokaRoom.query.filter_by(room_code=room_code).first()
    if not room:
        return jsonify({"error": "房间不存在"}), 404
    game = BokaGame.query.filter_by(room_id=room.id).order_by(BokaGame.id.desc()).first()
    if not game or game.phase != "selecting":
        return jsonify({"error": "当前不可投降"}), 400
    me = BokaGamePlayer.query.filter_by(game_id=game.id, username=current_user.username).first()
    if not me or me.surrendered:
        return jsonify({"error": "你无法投降"}), 400
    all_players = BokaGamePlayer.query.filter_by(game_id=game.id).all()
    alive_count = sum(1 for g in all_players if not g.surrendered and len(json_loads_safe(g.hand)) > 0)
    me.surrendered = True
    me.surrendered_rank = alive_count
    me.hand = json_dumps_safe([])
    me.ready_card = json_dumps_safe([])
    me.locked = True
    db.session.commit()
    alive = [g for g in all_players if not g.surrendered and len(json_loads_safe(g.hand)) > 0]
    if len(alive) <= 1:
        finish_boka_game(game, alive)
        return jsonify({"success": True, "rank": me.surrendered_rank, "finished": True})
    return jsonify({"success": True, "rank": me.surrendered_rank, "finished": False})

def calc_boka_layout(n, my_username, players):
    if n == 1:
        areas = {"bottom": 1}
    else:
        rest = n - 1
        top = 1
        rest -= 1
        if rest % 2 == 1:
            top += 1
            rest -= 1
        left = rest // 2
        right = rest // 2
        areas = {"top": top, "left": left, "right": right, "bottom": 1}
    others = [p for p in players if p.username != my_username]
    result = {}
    result[my_username] = {"side": "bottom", "index": 0}
    idx = 0
    for side in ["top", "left", "right"]:
        count = areas.get(side, 0)
        for i in range(count):
            if idx >= len(others):
                break
            result[others[idx].username] = {"side": side, "index": i}
            idx += 1
    return result

# ========== 世界 Boss ==========
@app.route('/world_boss')
@login_required
def world_boss():
    wb = ensure_world_boss()
    current_week = wb.week_num
    if current_user.boss_fatigue_week != current_week:
        current_user.set_boss_fatigue({})
        current_user.boss_fatigue_week = current_week
        db.session.commit()
    today_weak = get_today_weak_attr(wb)
    today_weak_cn = ATTR_CN[today_weak]
    today_color = ATTR_COLORS[today_weak]
    coll = ensure_collection_migrated(current_user)
    owned_ids = set(int(cid) for cid in coll.keys() if coll[cid].get("count", 0) > 0)
    owned = [c for c in CARDS if c["id"] in owned_ids]
    fatigue = current_user.get_boss_fatigue()

    from bonds_data import (RELATION_BONDS, REGION_BONDS, POSITION_BONDS, ENEMY_BONDS)
    from game_logic import (calc_relation_bonus, calc_region_bonus, calc_position_bonus, calc_enemy_bonus)

    decks = BossDeck.query.filter_by(user_id=current_user.id).all()
    my_decks = []
    for d in decks:
        card_ids = json_loads_safe(d.card_ids)
        cards = [CARD_BY_ID.get(cid) for cid in card_ids if CARD_BY_ID.get(cid)]
        dmg = boss_deck_damage_with_bond(cards, today_weak, fatigue) if cards else 0
        names = [c["name"] for c in cards] if cards else []
        rel = calc_relation_bonus(names) if names else {}
        reg = calc_region_bonus(names) if names else {}
        pos = calc_position_bonus(names) if names else {}
        ene = calc_enemy_bonus(names) if names else {}
        active_bonds = []
        if rel:
            best_val = max(rel.values())
            for bond in RELATION_BONDS:
                hit_bond = None
                for g in bond["groups"]:
                    if all(n in names for n in g) and rel.get(g[0], None) == best_val:
                        hit_bond = {"name": bond["name"], "members": g}
                        break
                if hit_bond:
                    active_bonds.append({"type": "relation", "name": hit_bond["name"], "members": hit_bond["members"], "value": best_val})
                    break
        if reg:
            best_val = max(reg.values())
            for bond in REGION_BONDS:
                hit = [n for n in bond["members"] if n in names]
                if len(hit) >= 2 and reg.get(hit[0], None) == best_val:
                    active_bonds.append({"type": "region", "name": bond["name"], "members": hit, "value": best_val})
                    break
        if pos:
            best_val = max(pos.values())
            for bond in POSITION_BONDS:
                hit = [n for n in bond["members"] if n in names]
                if len(hit) >= 2 and pos.get(hit[0], None) == best_val:
                    active_bonds.append({"type": "position", "name": bond["name"], "members": hit, "value": best_val})
                    break
        if ene:
            worst_val = max(ene.values())
            for bond in ENEMY_BONDS:
                for g in bond["groups"]:
                    if all(n in names for n in g) and ene.get(g[0], None) == worst_val:
                        active_bonds.append({"type": "enemy", "name": bond["name"], "members": g, "value": worst_val})
                        break
                else:
                    continue
                break
        for c in cards:
            my_bonds = []
            for b in active_bonds:
                if c["name"] in b["members"]:
                    my_bonds.append(b)
            c["my_bonds"] = my_bonds
        my_decks.append({"id": d.id, "name": d.name or f"卡组{d.id}", "cards": cards, "damage": dmg, "bonds": active_bonds})

    my_dmg = BossDamage.query.filter_by(user_id=current_user.id, week_num=current_week).first()
    my_total_damage = my_dmg.total_damage if my_dmg else 0
    all_records = BossDamage.query.filter_by(week_num=current_week).order_by(BossDamage.total_damage.desc()).all()
    ranks = []
    for idx, r in enumerate(all_records, start=1):
        u = User.query.get(r.user_id)
        if u:
            ranks.append({"rank": idx, "nickname": u.nickname or u.username,
                          "username": u.username, "avatar": f"/static/avatars/{u.username}.jpg",
                          "damage": r.total_damage, "is_me": r.user_id == current_user.id})
    today_count = get_today_battle_count(current_user.id)
    remaining = max(0, BOSS_DAILY_LIMIT - today_count)
    active_battle = get_active_battle(current_user.id)
    active_battle_data = None
    if active_battle:
        card_ids = json_loads_safe(active_battle.card_ids)
        cards = [CARD_BY_ID.get(cid) for cid in card_ids if CARD_BY_ID.get(cid)]
        now = datetime.now()
        total_secs = int((active_battle.ends_at - active_battle.started_at).total_seconds())
        passed = int((now - active_battle.started_at).total_seconds())
        progress = min(100, max(0, int(passed / total_secs * 100))) if total_secs else 100
        is_finished = now >= active_battle.ends_at
        active_battle_data = {"id": active_battle.id, "cards": cards, "progress": progress,
                              "is_finished": is_finished, "damage": active_battle.damage,
                              "started_at": active_battle.started_at.strftime("%H:%M"),
                              "ends_at": active_battle.ends_at.strftime("%H:%M")}
    next_week = get_next_week_start()
    retreat_str = f"{next_week.month}月{next_week.day}日6时撤退"
    return render_template('world_boss.html',
                           boss={"name": wb.boss_name, "troop": wb.boss_troop},
                           hp_current=wb.current_hp, hp_max=wb.max_hp,
                           hp_percent=max(0, int(wb.current_hp / wb.max_hp * 100)) if wb.max_hp else 0,
                           today_weak=today_weak, today_weak_cn=today_weak_cn, today_color=today_color,
                           retreat_str=retreat_str, killed=wb.current_hp <= 0,
                           cards=owned, fatigue=fatigue, decks=my_decks,
                           my_total_damage=my_total_damage, ranks=ranks,
                           today_count=today_count, remaining=remaining,
                           active_battle=active_battle_data)

@app.route('/world_boss/picker')
@login_required
def world_boss_picker():
    deck_id = request.args.get('deck_id')
    coll = ensure_collection_migrated(current_user)
    owned_ids = set(int(cid) for cid in coll.keys() if coll[cid].get("count", 0) > 0)
    owned = [c for c in CARDS if c["id"] in owned_ids]
    selected_ids = []
    deck_name = ""
    if deck_id:
        d = BossDeck.query.filter_by(id=deck_id, user_id=current_user.id).first()
        if d:
            selected_ids = json_loads_safe(d.card_ids)
            deck_name = d.name or f"卡组{d.id}"
    return render_template('world_boss_picker.html', cards=owned,
                           selected_ids=selected_ids, deck_id=deck_id or "", deck_name=deck_name)

@app.route('/world_boss/deck/new', methods=['POST'])
@login_required
def world_boss_deck_new():
    count = BossDeck.query.filter_by(user_id=current_user.id).count()
    if count >= 20:
        return jsonify({"error": "最多 20 个卡组"}), 400
    return jsonify({"success": True, "name": f"卡组{count + 1}"})

@app.route('/world_boss/deck/save', methods=['POST'])
@login_required
def world_boss_deck_save():
    deck_id = request.json.get('deck_id')
    card_ids = request.json.get('card_ids', [])
    name = request.json.get('name', '').strip()
    if not isinstance(card_ids, list) or len(card_ids) < 1 or len(card_ids) > 5:
        return jsonify({"error": "卡组需 1~5 张卡"}), 400
    coll = ensure_collection_migrated(current_user)
    for cid in card_ids:
        entry = coll.get(str(cid))
        if not entry or entry["count"] <= 0:
            return jsonify({"error": "拥有卡不足"}), 400
    if deck_id:
        d = BossDeck.query.filter_by(id=deck_id, user_id=current_user.id).first()
        if not d:
            return jsonify({"error": "卡组不存在"}), 404
    else:
        count = BossDeck.query.filter_by(user_id=current_user.id).count()
        if count >= 20:
            return jsonify({"error": "最多 20 个卡组"}), 400
        d = BossDeck(user_id=current_user.id, created_at=datetime.now())
        db.session.add(d)
    d.card_ids = json_dumps_safe(card_ids)
    if name:
        d.name = name[:50]
    db.session.commit()
    return jsonify({"success": True, "deck_id": d.id, "name": d.name})

@app.route('/world_boss/deck/delete', methods=['POST'])
@login_required
def world_boss_deck_delete():
    deck_id = request.json.get('deck_id')
    d = BossDeck.query.filter_by(id=deck_id, user_id=current_user.id).first()
    if not d:
        return jsonify({"error": "卡组不存在"}), 404
    db.session.delete(d)
    db.session.commit()
    return jsonify({"success": True})

@app.route('/world_boss/deck/rename', methods=['POST'])
@login_required
def world_boss_deck_rename():
    deck_id = request.json.get('deck_id')
    name = request.json.get('name', '').strip()[:50]
    if not name:
        return jsonify({"error": "名字不能为空"}), 400
    d = BossDeck.query.filter_by(id=deck_id, user_id=current_user.id).first()
    if not d:
        return jsonify({"error": "卡组不存在"}), 404
    d.name = name
    db.session.commit()
    return jsonify({"success": True, "name": name})

@app.route('/world_boss/attack', methods=['POST'])
@login_required
def world_boss_attack():
    deck_id = request.json.get('deck_id')
    d = BossDeck.query.filter_by(id=deck_id, user_id=current_user.id).first()
    if not d:
        return jsonify({"error": "卡组不存在"}), 404
    active = get_active_battle(current_user.id)
    if active:
        return jsonify({"error": "已有队伍出战中"}), 400
    today_count = get_today_battle_count(current_user.id)
    if today_count >= BOSS_DAILY_LIMIT:
        return jsonify({"error": "今日出战次数已用完"}), 400
    card_ids = json_loads_safe(d.card_ids)
    cards = [CARD_BY_ID.get(cid) for cid in card_ids if CARD_BY_ID.get(cid)]
    if not cards:
        return jsonify({"error": "卡组为空"}), 400
    wb = ensure_world_boss()
    today_weak = get_today_weak_attr(wb)
    fatigue = current_user.get_boss_fatigue()
    damage = boss_deck_damage_with_bond(cards, today_weak, fatigue)
    now = datetime.now()
    battle = BossBattle(
        user_id=current_user.id, week_num=wb.week_num, deck_id=d.id,
        card_ids=json_dumps_safe(card_ids), damage=damage,
        started_at=now, ends_at=now + timedelta(hours=BOSS_BATTLE_DURATION_HOURS),
        finished=False,
    )
    db.session.add(battle)
    for c in cards:
        cid = str(c["id"])
        fatigue[cid] = fatigue.get(cid, 0) + 1
    current_user.set_boss_fatigue(fatigue)
    db.session.commit()
    return jsonify({"success": True, "battle_id": battle.id, "damage": damage})

@app.route('/world_boss/finish', methods=['POST'])
@login_required
def world_boss_finish():
    battle_id = request.json.get('battle_id')
    b = BossBattle.query.filter_by(id=battle_id, user_id=current_user.id, finished=False).first()
    if not b:
        return jsonify({"error": "出战记录不存在"}), 404
    now = datetime.now()
    if now < b.ends_at:
        return jsonify({"error": "还没到时间"}), 400
    wb = ensure_world_boss()
    if wb.current_hp > 0:
        wb.current_hp = max(0, wb.current_hp - b.damage)
        if wb.current_hp == 0 and wb.killed_at is None:
            wb.killed_at = datetime.now()
    record = BossDamage.query.filter_by(user_id=current_user.id, week_num=wb.week_num).first()
    if not record:
        record = BossDamage(user_id=current_user.id, week_num=wb.week_num, total_damage=0)
        db.session.add(record)
    record.total_damage += b.damage
    record.last_hit_at = now
    db.session.delete(b)
    db.session.commit()
    return jsonify({"success": True, "damage": b.damage,
                    "hp_current": wb.current_hp, "hp_max": wb.max_hp,
                    "killed": wb.current_hp <= 0})

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

@app.route('/change_password', methods=['POST'])
@login_required
def change_password():
    old = request.form.get('old_password', '')
    new = request.form.get('new_password', '')
    confirm = request.form.get('confirm_password', '')
    trophies = current_user.get_champion_months()
    if not current_user.check_password(old):
        return render_template('profile.html', error='当前密码错误', trophies=trophies,
                               boka_best=current_user.boka_best_score,
                               boka_best_time=current_user.boka_best_time,
                               boss_best=current_user.boss_best_damage,
                               boss_best_time=current_user.boss_best_time)
    if new != confirm:
        return render_template('profile.html', error='两次密码不一致', trophies=trophies,
                               boka_best=current_user.boka_best_score,
                               boka_best_time=current_user.boka_best_time,
                               boss_best=current_user.boss_best_damage,
                               boss_best_time=current_user.boss_best_time)
    current_user.set_password(new)
    db.session.commit()
    return render_template('profile.html', error='密码修改成功', trophies=trophies,
                           boka_best=current_user.boka_best_score,
                           boka_best_time=current_user.boka_best_time,
                           boss_best=current_user.boss_best_damage,
                           boss_best_time=current_user.boss_best_time)

@app.route('/upload_avatar', methods=['POST'])
@login_required
def upload_avatar():
    file = request.files.get('avatar')
    if not file:
        return redirect(url_for('profile'))
    filename = f"{current_user.username}.jpg"
    path = os.path.join(app.static_folder, 'avatars', filename)
    file.save(path)
    current_user.last_avatar_change = datetime.now()
    db.session.commit()
    return redirect(url_for('profile'))

@app.route('/user/<username>')
@login_required
def user_profile(username):
    user = User.query.filter_by(username=username).first()
    if not user:
        return "玩家不存在", 404
    trophies = user.get_champion_months()
    return render_template('user_profile.html',
                           profile_user=user, trophies=trophies,
                           boka_best=user.boka_best_score,
                           boka_best_time=user.boka_best_time,
                           boss_best=user.boss_best_damage,
                           boss_best_time=user.boss_best_time)

# ========== 临时创建账号 ==========
@app.route('/init_accounts')
def init_accounts():
    ACCOUNTS = [
        ("gelu", "gelu", "格鲁"), ("benlei", "benlei", "奔雷"),
        ("nanju", "nanju", "楠局"), ("jiangzha", "jiangzha", "蒋渣"),
        ("shuanan", "shuanan", "耍男"), ("chenran", "chenran", "陈然"),
        ("diaonan", "diaonan", "吊男"), ("biesan", "biesan", "瘪三"),
        ("zhengwei", "zhengwei", "政委"), ("jiangmen", "jiangmen", "姜门"),
        ("xiaoxu", "xiaoxu", "小旭"), ("kaxiang", "kaxiang", "卡翔"),
        ("tieniu", "tieniu", "铁牛"), ("denghuang", "denghuang", "登黄"),
        ("tianhua", "tianhua", "天花"), ("haohao", "haohao", "浩浩"),
        ("lafang", "lafang", "拉芳"),
    ]
    created = []
    for username, password, nickname in ACCOUNTS:
        u = User.query.filter_by(username=username).first()
        if u:
            u.gold = 10
            u.collection = "{}"
            u.collection_migrated = True
            u.silver = 0
            u.copper = 0
            u.boka_room_id = None
            created.append(f"重置：{username}")
        else:
            u = User(username=username, nickname=nickname)
            u.set_password(password)
            u.gold = 10
            u.collection_migrated = True
            db.session.add(u)
            created.append(f"已创建：{username}")
    db.session.commit()
    return "<br>".join(created)

# ========== 启动 ==========
with app.app_context():
    db.create_all()
    from sqlalchemy import text
    migration_sql = [
        'ALTER TABLE "user" ADD COLUMN IF NOT EXISTS collection_migrated BOOLEAN DEFAULT FALSE',
        'ALTER TABLE "user" ADD COLUMN IF NOT EXISTS boss_fatigue_week INTEGER DEFAULT 0',
        'ALTER TABLE "user" ADD COLUMN IF NOT EXISTS boka_room_id INTEGER',
        'ALTER TABLE "user" ADD COLUMN IF NOT EXISTS max_score INTEGER DEFAULT 0',
        'ALTER TABLE "boka_game" ADD COLUMN IF NOT EXISTS revealed_at TIMESTAMP',
        'ALTER TABLE "boka_game" ADD COLUMN IF NOT EXISTS round_winner_card_id INTEGER',
        'ALTER TABLE "boka_game" ADD COLUMN IF NOT EXISTS beauty_left INTEGER DEFAULT 3',
    ]
    try:
        with db.engine.begin() as conn:
            for sql in migration_sql:
                conn.execute(text(sql))
        print("✅ DB migration done")
    except Exception as e:
        print("⚠️ DB migration error:", e)

    try:
        empty_decks = BossDeck.query.all()
        removed = 0
        for d in empty_decks:
            ids = json_loads_safe(d.card_ids)
            if not ids:
                db.session.delete(d)
                removed += 1
        if removed:
            db.session.commit()
            print(f"🧹 清理了 {removed} 个空卡组")
    except Exception as e:
        print("⚠️ 清理空卡组出错:", e)

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=int(os.getenv('PORT', 5000)))
