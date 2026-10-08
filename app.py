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
    "白": "#d0d0d0",
    "绿": "#5cb85c",
    "蓝": "#4a90d9",
    "紫": "#a06cd5",
    "橙": "#f5a623",
}

# 五维属性代表色
ATTR_COLORS = {
    "lead": "#c8e0c8",
    "might": "#e8c8b8",
    "intel": "#d8c8e8",
    "politics": "#f0dcb0",
    "charm": "#e8b8c8",
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
# 世界 Boss 第 1 周基准日：2026-10-05（周一）6:00
BOSS_EPOCH_MONDAY = datetime(2026, 10, 5, 6, 0, 0)

def get_current_week_num():
    """从基准日开始算，本周 = 1。"""
    now = datetime.now()
    weekday = now.weekday()
    monday_6 = now.replace(hour=6, minute=0, second=0, microsecond=0)
    if weekday > 0 or now < monday_6:
        monday_6 = monday_6 - timedelta(days=weekday if weekday > 0 else 7)
    delta_days = (monday_6 - BOSS_EPOCH_MONDAY).days
    return max(1, delta_days // 7 + 1)
    
def get_current_week_start():
    """返回本周一 6:00 的 datetime"""
    now = datetime.now()
    weekday = now.weekday()
    monday_6 = now.replace(hour=6, minute=0, second=0, microsecond=0)
    if weekday > 0 or now < monday_6:
        monday_6 = monday_6 - timedelta(days=weekday if weekday > 0 else 7)
    return monday_6

def get_next_week_start():
    """下周一 6:00（撤退时间）"""
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
            id=1,
            week_num=current_week,
            boss_name=boss["name"],
            boss_troop=boss["troop"],
            max_hp=max_hp,
            current_hp=max_hp,
            weak_schedule=json_dumps_safe(generate_weak_schedule()),
            started_at=datetime.now(),
            payout_done=False,
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

# ========== 世界 Boss 出战辅助 ==========
def get_today_battle_count(user_id):
    """今天 6 点之后，此玩家已出战次数"""
    today_start = get_current_week_start()  # 本周一 6 点
    # 更精确：取今天 6 点
    now = datetime.now()
    today_6 = now.replace(hour=6, minute=0, second=0, microsecond=0)
    if now < today_6:
        today_6 = today_6 - timedelta(days=1)
    count = BossBattle.query.filter(
        BossBattle.user_id == user_id,
        BossBattle.started_at >= today_6,
        BossBattle.finished == False,
    ).count()
    # finished 的也算出战次数（今天用掉的次数）
    count_total = BossBattle.query.filter(
        BossBattle.user_id == user_id,
        BossBattle.started_at >= today_6,
    ).count()
    return count_total

def get_active_battle(user_id):
    """拿到当前未收兵的出战记录（同一时间只能有一个）"""
    return BossBattle.query.filter_by(user_id=user_id, finished=False).first()

# ========== 自定义静态文件路由 ==========
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
            **card,
            "count": count,
            "level": level,
            "quality": quality,
            "star": star,
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
                           buildings=result,
                           cards=owned,
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
                           cards=owned,
                           deployed=deployed,
                           bid=int(bid))

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
def gen_room_code():
    """生成唯一 6 位房间码"""
    chars = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    for _ in range(50):
        code = ''.join(random.choices(chars, k=6))
        if not BokaRoom.query.filter_by(room_code=code).first():
            return code
    return ''.join(random.choices(chars, k=6))

@app.route('/boka')
@login_required
def boka():
    # 计算我的排名（积分榜）
    all_users = User.query.order_by(User.score.desc()).all()
    my_rank = 0
    for idx, u in enumerate(all_users, start=1):
        if u.id == current_user.id:
            my_rank = idx
            break
    # 我的场次：暂时用 0（后面战绩表可加）
    return render_template('boka.html',
                           games=0,
                           score=current_user.score,
                           rank=my_rank)

@app.route('/boka/create', methods=['POST'])
@login_required
def boka_create():
    # 如果已在别的房间，先退出
    leave_any_room(current_user)

    code = gen_room_code()
    room = BokaRoom(
        room_code=code,
        owner_username=current_user.username,
        status="waiting",
        max_players=14,
        created_at=datetime.now(),
    )
    db.session.add(room)
    db.session.flush()  # 拿到 room.id

    p = BokaPlayer(
        room_id=room.id,
        username=current_user.username,
        nickname=current_user.nickname or current_user.username,
        ready=False,
        seat=0,
        joined_at=datetime.now(),
    )
    db.session.add(p)
    current_user.boka_room_id = room.id
    db.session.commit()
    return jsonify({"room_id": code})

@app.route('/boka/rooms')
@login_required
def boka_rooms():
    """列出所有 waiting 状态的房间"""
    rooms = BokaRoom.query.filter_by(status="waiting").order_by(BokaRoom.created_at.desc()).all()
    result = []
    for r in rooms:
        players = BokaPlayer.query.filter_by(room_id=r.id).all()
        result.append({
            "room_id": r.room_code,
            "status": "准备中",
            "count": len(players),
            "owner": r.owner_username,
            "players": [
                {"name": p.nickname or p.username,
                 "username": p.username,
                 "avatar": f"/static/avatars/{p.username}.jpg",
                 "is_owner": p.username == r.owner_username}
                for p in players
            ],
            "joined": any(p.username == current_user.username for p in players),
        })
    return jsonify({"rooms": result})

def leave_any_room(user):
    """把用户从任何房间移除（如果不是房主；若是房主则解散房间）"""
    if not user.boka_room_id:
        return
    room = BokaRoom.query.get(user.boka_room_id)
    if room:
        if room.owner_username == user.username:
            # 房主离开 = 解散
            BokaPlayer.query.filter_by(room_id=room.id).delete()
            db.session.delete(room)
        else:
            BokaPlayer.query.filter_by(room_id=room.id, username=user.username).delete()
    user.boka_room_id = None

@app.route('/boka/room/<room_code>')
@login_required
def boka_room(room_code):
    room = BokaRoom.query.filter_by(room_code=room_code).first()
    if not room:
        return redirect(url_for('boka'))

    # 如果我不在这个房间，加入
    me = BokaPlayer.query.filter_by(room_id=room.id, username=current_user.username).first()
    if not me:
        # 先离开其他房间
        if current_user.boka_room_id and current_user.boka_room_id != room.id:
            leave_any_room(current_user)
            db.session.commit()
            room = BokaRoom.query.filter_by(room_code=room_code).first()
            if not room:
                return redirect(url_for('boka'))
            me = BokaPlayer.query.filter_by(room_id=room.id, username=current_user.username).first()

        if not me:
            player_count = BokaPlayer.query.filter_by(room_id=room.id).count()
            if player_count >= room.max_players:
                return "房间已满", 403
            me = BokaPlayer(
                room_id=room.id,
                username=current_user.username,
                nickname=current_user.nickname or current_user.username,
                ready=False,
                seat=player_count,
                joined_at=datetime.now(),
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

    # 如果已离开（暂离状态），进来就恢复
    if me.is_temporary_away:
        me.is_temporary_away = False
        db.session.commit()

    return render_template('boka_room.html',
                           room_code=room.room_code,
                           room_id=room.id,
                           invite_url=request.url,
                           ready_count=ready_count,
                           player_count=len(players),
                           is_ready=is_ready,
                           is_owner=is_owner,
                           players=[
                               {"username": p.username,
                                "nickname": p.nickname or p.username,
                                "is_owner": p.username == room.owner_username,
                                "ready": p.ready,
                                "is_away": p.is_temporary_away}
                               for p in players
                           ])

@app.route('/boka/room/<room_code>/state')
@login_required
def boka_room_state(room_code):
    """轮询用：返回房间状态"""
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
            {"username": p.username,
             "nickname": p.nickname or p.username,
             "is_owner": p.username == room.owner_username,
             "ready": p.ready,
             "is_away": p.is_temporary_away}
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

    # 检查班级收藏
    class_records = ClassCollection.query.all()
    if not class_records:
        return jsonify({"error": "班级收藏册为空，无法开始"}), 400

    class_card_ids = [r.card_id for r in class_records]

    # 优先池：36 天罡 + 6 地煞 = 42 张
    PRIORITY_EXTRA = ["扈三娘", "凌振", "陶宗旺", "樊瑞", "白胜", "孙二娘"]
    priority_ids = []
    for c in CARDS:
        if c["id"] <= 36 or c["name"] in PRIORITY_EXTRA:
            priority_ids.append(c["id"])

    # 优先池 ∩ 班级收藏
    available_priority = [cid for cid in priority_ids if cid in class_card_ids]
    # 非优先池
    available_rest = [cid for cid in class_card_ids if cid not in priority_ids]

    # 卡池 = 优先池 42 张（若班级收藏里够）+ 其余随机补足至 42
    random.shuffle(available_priority)
    random.shuffle(available_rest)
    pool = available_priority[:42]
    if len(pool) < 42:
        need = 42 - len(pool)
        pool += available_rest[:need]

    if len(pool) < len(players):
        return jsonify({"error": "班级收藏卡不足"}), 400

    # 创建对局
    game = BokaGame(
        room_id=room.id,
        round_no=0,
        phase="waiting",
        card_pool=json_dumps_safe(pool),
        history=json_dumps_safe([]),
        created_at=datetime.now(),
    )
    db.session.add(game)
    db.session.flush()

    # 发牌：每人 min(6, len(pool) // n) 张
    n = len(players)
    cards_per_player = min(6, len(pool) // n)

    # 洗牌
    random.shuffle(pool)
    for i, p in enumerate(players):
        start = i * cards_per_player
        end = start + cards_per_player
        hand = pool[start:end]
        gp = BokaGamePlayer(
            game_id=game.id,
            username=p.username,
            nickname=p.nickname or p.username,
            hand=json_dumps_safe(hand),
            ready_card=json_dumps_safe([]),
            locked=False,
        )
        db.session.add(gp)

    # 剩下的牌留在卡袋（pool[cards_per_player * n:]）
    remaining_pool = pool[cards_per_player * n:]
    game.card_pool = json_dumps_safe(remaining_pool)

    # 更新房间状态
    room.status = "playing"
    room.started_at = datetime.now()

    # 初始化第 1 轮
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

    # 清掉所有成员的 boka_room_id
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
    """暂离房间：保留座位，标记 is_temporary_away"""
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
    """彻底退出房间"""
    room = BokaRoom.query.filter_by(room_code=room_code).first()
    if not room:
        return jsonify({"error": "房间不存在"}), 404
    if room.owner_username == current_user.username:
        # 房主退出 = 解散
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

    # 拿到本局
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
            "username": g.username,
            "nickname": g.nickname,
            "is_me": g.username == current_user.username,
            "hand_count": len(json_loads_safe(g.hand)),
            "locked": g.locked,
        })

    round_phase = "比攻" if game.round_no % 2 == 1 else "比防"
    return render_template('boka_battle.html',
                           room_code=room_code,
                           room_id=room.id,
                           game_id=game.id,
                           round_no=game.round_no,
                           round_phase=round_phase,
                           phase=game.phase,
                           players=players_view,
                           layout=layout,
                           hand=my_hand,
                           my_ready=json_loads_safe(me.ready_card) if me else [])

@app.route('/boka/room/<room_code>/play', methods=['POST'])
@login_required
def boka_play(room_code):
    """玩家点出战：把自己的备战区锁定"""
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

    # 校验卡在手牌
    my_hand = json_loads_safe(me.hand)
    for cid in card_ids:
        if cid not in my_hand:
            return jsonify({"error": f"卡 {cid} 不在手牌"}), 400

    me.ready_card = json_dumps_safe(card_ids)
    me.locked = True
    db.session.commit()

    # 检查是否所有人都锁定了
    all_players = BokaGamePlayer.query.filter_by(game_id=game.id).all()
    if all(p.locked for p in all_players):
        # 全部锁定 → 结算本轮
        resolve_boka_round(game)

    return jsonify({"success": True})

@app.route('/boka/room/<room_code>/battle_state')
@login_required
def boka_battle_state(room_code):
    """轮询战斗状态"""
    room = BokaRoom.query.filter_by(room_code=room_code).first()
    if not room:
        return jsonify({"error": "房间不存在"}), 404
    game = BokaGame.query.filter_by(room_id=room.id).order_by(BokaGame.id.desc()).first()
    if not game:
        return jsonify({"error": "无对局"}), 404

    # 检查 revealing 阶段是否已过 3 秒
    if game.phase == "revealing" and game.revealed_at:
        elapsed = (datetime.now() - game.revealed_at).total_seconds()
        if elapsed >= 3.0:
            # 检查游戏是否已结束
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
        # 只在 revealing / finished 阶段展示所有人的卡
        # 或者自己能看到自己的卡
        show_cards = (game.phase in ("revealing", "finished")) or (g.username == current_user.username)
        players_view.append({
            "username": g.username,
            "nickname": g.nickname,
            "is_me": g.username == current_user.username,
            "hand_count": len(json_loads_safe(g.hand)),
            "locked": g.locked,
            "ready_cards": [
                CARD_BY_ID.get(cid) for cid in (ready_cards if show_cards else []) if CARD_BY_ID.get(cid)
            ],
            "rank": g.rank,
            "score_change": g.score_change or 0,
            "surrendered": g.surrendered,
        })

    my_hand_ids = json_loads_safe(me.hand) if me else []
    my_ready_ids = json_loads_safe(me.ready_card) if me else []

    return jsonify({
        "round_no": game.round_no,
        "phase": game.phase,
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
    })

def resolve_boka_round(game):
    """所有人都锁定后，结算本轮。
    流程：找出最大卡 → 更新手牌/卡袋 → 切到 revealing 状态
    下一轮由 boka_battle_state 在 3 秒后自动切换。
    """
    gps = BokaGamePlayer.query.filter_by(game_id=game.id).all()
    is_atk_round = (game.round_no % 2 == 1)
    dim = "atk" if is_atk_round else "def"
    other_dim = "def" if is_atk_round else "atk"

    played = []
    for g in gps:
        card_ids = json_loads_safe(g.ready_card)
        if not card_ids:
            continue
        cards = [CARD_BY_ID.get(cid) for cid in card_ids if CARD_BY_ID.get(cid)]
        if not cards:
            continue
        if len(cards) == 1:
            value = cards[0][dim]
            other = cards[0][other_dim]
            is_combo = False
        else:
            atk, dfn, combo_name = calc_combo_stats(cards)
            if atk is None:
                value = max(c[dim] for c in cards)
                other = max(c[other_dim] for c in cards)
                is_combo = False
            else:
                value = atk if is_atk_round else dfn
                other = dfn if is_atk_round else atk
                is_combo = True
        played.append({
            "username": g.username,
            "card_ids": card_ids,
            "value": value,
            "other": other,
            "is_combo": is_combo,
        })

    if not played:
        game.revealed_at = datetime.now()
        game.phase = "revealing"
        db.session.commit()
        return

    # 炸弹检测
    BOMB_NAMES = {"白胜", "孙二娘"}
    has_bomb = any(
        CARD_BY_ID.get(cid, {}).get("name") in BOMB_NAMES
        for p in played for cid in p["card_ids"]
    )
    immune = False
    if has_bomb:
        for p in played:
            if p["is_combo"]:
                cards = [CARD_BY_ID.get(cid) for cid in p["card_ids"]]
                _, _, combo_name = calc_combo_stats(cards)
                for combo in COMBOS:
                    if combo["name"] == combo_name and combo.get("special") in ("bomb_eater", "bomb_eater_steal1"):
                        immune = True
                        break
            if immune:
                break

    pool = json_loads_safe(game.card_pool)
    round_record = {"round": game.round_no, "dim": dim, "played": []}

    if has_bomb and not immune:
        # 炸弹生效：所有卡进卡袋
        for p in played:
            pool.extend(p["card_ids"])
            g = next(x for x in gps if x.username == p["username"])
            hand = json_loads_safe(g.hand)
            hand = [cid for cid in hand if cid not in p["card_ids"]]
            g.hand = json_dumps_safe(hand)
            g.ready_card = json_dumps_safe([])
            g.locked = False
            cards = [CARD_BY_ID.get(cid) for cid in p["card_ids"]]
            round_record["played"].append({
                "username": p["username"],
                "cards": [{"id": c["id"], "name": c["name"], "atk": c["atk"], "def": c["def"]} for c in cards],
                "value": p["value"],
                "result": "bombed",
            })
        game.round_winner_card_id = None
        game.winner_username = None
    else:
        # 正常比大小
        best = max(played, key=lambda x: (x["value"], x["other"]))
        best_value = best["value"]
        best_other = best["other"]
        winners = [p for p in played if p["value"] == best_value and p["other"] == best_other]
        winner = winners[0]

        winner_g = next(x for x in gps if x.username == winner["username"])
        winner_hand = json_loads_safe(winner_g.hand)

        # 找最大卡
        max_card_id = max(
            winner["card_ids"],
            key=lambda cid: (CARD_BY_ID.get(cid, {}).get(dim, 0), CARD_BY_ID.get(cid, {}).get(other_dim, 0))
        )

        for p in played:
            g = next(x for x in gps if x.username == p["username"])
            hand = json_loads_safe(g.hand)
            hand = [cid for cid in hand if cid not in p["card_ids"]]

            if p["username"] == winner["username"]:
                # 赢家：最大卡进卡袋，其他所有卡（含自己的其他）进手牌
                pool.append(max_card_id)
                for cid in p["card_ids"]:
                    if cid != max_card_id:
                        hand.append(cid)
            else:
                # 输家：所有打出的卡给赢家
                winner_hand.extend(p["card_ids"])

            g.hand = json_dumps_safe(hand)
            g.ready_card = json_dumps_safe([])
            g.locked = False

            cards = [CARD_BY_ID.get(cid) for cid in p["card_ids"]]
            round_record["played"].append({
                "username": p["username"],
                "cards": [{"id": c["id"], "name": c["name"], "atk": c["atk"], "def": c["def"]} for c in cards],
                "value": p["value"],
                "result": "win" if p["username"] == winner["username"] else "lose",
            })

        winner_g.hand = json_dumps_safe(winner_hand)
        game.round_winner_card_id = max_card_id
        game.winner_username = winner["username"]

    # 检查出完手牌的人
    for g in gps:
        hand = json_loads_safe(g.hand)
        if len(hand) == 0 and g.finished_order is None and not g.surrendered:
            max_order = db.session.query(db.func.max(BokaGamePlayer.finished_order)).filter_by(game_id=game.id).scalar() or 0
            g.finished_order = max_order + 1

    # 游戏是否结束
    alive = [g for g in gps if len(json_loads_safe(g.hand)) > 0 and not g.surrendered]
    game.card_pool = json_dumps_safe(pool)
    history = json_loads_safe(game.history)
    history.append(round_record)
    game.history = json_dumps_safe(history)

    if len(alive) <= 1:
        # 结束
        finish_boka_game(game, alive)
    else:
        # 进入 revealing 阶段（3 秒后由 battle_state 切下一轮）
        game.phase = "revealing"
        game.revealed_at = datetime.now()

    db.session.commit()

def finish_boka_game(game, alive):
    """游戏结束，计算名次、积分"""
    gps = BokaGamePlayer.query.filter_by(game_id=game.id).all()

    # 名次：
    # 最后还有手牌的人（alive[0]） = 第 1 名
    # 按 finished_order 倒序：finished_order 越大越晚出完（越晚出完名次越高）
    # 实际：finished_order = 1 表示最先出完 = 倒数第一

    # 处理：
    # - 有 finished_order 的人：按 finished_order 降序排（大的在前面）
    # - 无 finished_order 的人（投降或最后存活）：投降的按 surrendered_rank，存活的排第 1
    survivors = [g for g in gps if g.username in [a.username for a in alive]]
    finished = [g for g in gps if g.finished_order is not None]
    surrendered = [g for g in gps if g.surrendered]

    finished.sort(key=lambda g: g.finished_order, reverse=True)

    rank_order = []
    if survivors:
        # 第 1 名（可能多个）
        for s in survivors:
            rank_order.append(s)
    for f in finished:
        rank_order.append(f)
    for s in surrendered:
        if s not in rank_order:
            rank_order.append(s)

    n = len(rank_order)
    # 计算对手平均分
    all_scores = [User.query.filter_by(username=g.username).first().score or 0 for g in rank_order]
    avg_score = sum(all_scores) / n if n else 0

    for idx, g in enumerate(rank_order, start=1):
        g.rank = idx

    # 结算积分（暂不做空气墙，只是基础分 + 系数）
    for g in rank_order:
        u = User.query.filter_by(username=g.username).first()
        if not u:
            continue
        old_score = u.score or 0
        change = calc_boka_score_change(old_score, g.rank, n, avg_score)
        new_score = old_score + change
        # 空气墙：每 1000 分一道
        floor = (new_score // 1000) * 1000
        if new_score < floor:
            new_score = floor
        g.score_change = new_score - old_score
        u.score = new_score

        # 记战绩
        rec = BokaGameRecord(
            username=g.username,
            game_id=game.id,
            room_code=None,
            rank=g.rank,
            player_count=n,
            score_before=old_score,
            score_change=g.score_change,
            score_after=new_score,
            played_at=datetime.now(),
        )
        db.session.add(rec)

    game.phase = "finished"
    game.finished_at = datetime.now()
    db.session.commit()

    # 房间回到 waiting
    room = BokaRoom.query.get(game.room_id)
    if room:
        room.status = "waiting"
        # 重置所有玩家准备
        BokaPlayer.query.filter_by(room_id=room.id).update({"ready": False})
        db.session.commit()

def calc_boka_score_change(my_score, rank, total_players, avg_score):
    """计算搏卡一局的积分变化"""
    # 基础分表（按人数、名次）
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

    # 系数：低分赢加得多，高分赢加得少
    coef = 1 + 0.5 * math.log((avg_score + 1000) / (my_score + 1000))
    coef = max(0.5, min(3.0, coef))

    if base >= 0:
        return int(base * coef)
    else:
        return -int(-base / coef)

@app.route('/boka/room/<room_code>/surrender', methods=['POST'])
@login_required
def boka_surrender(room_code):
    """投降弃卡：清空手牌，按当前剩余人数定名次"""
    room = BokaRoom.query.filter_by(room_code=room_code).first()
    if not room:
        return jsonify({"error": "房间不存在"}), 404
    game = BokaGame.query.filter_by(room_id=room.id).order_by(BokaGame.id.desc()).first()
    if not game or game.phase != "selecting":
        return jsonify({"error": "当前不可投降"}), 400

    me = BokaGamePlayer.query.filter_by(game_id=game.id, username=current_user.username).first()
    if not me or me.surrendered:
        return jsonify({"error": "你无法投降"}), 400

    # 计算当前存活人数
    all_players = BokaGamePlayer.query.filter_by(game_id=game.id).all()
    alive_count = sum(1 for g in all_players if not g.surrendered and len(json_loads_safe(g.hand)) > 0)
    me.surrendered = True
    me.surrendered_rank = alive_count  # 当前剩 N 人，投降就是第 N 名
    me.hand = json_dumps_safe([])
    me.ready_card = json_dumps_safe([])
    me.locked = True
    db.session.commit()

    # 检查是否全部投降或游戏结束
    alive = [g for g in all_players if not g.surrendered and len(json_loads_safe(g.hand)) > 0]
    if len(alive) <= 1:
        finish_boka_game(game, alive)

    return jsonify({"success": True, "rank": me.surrendered_rank})

def calc_boka_layout(n, my_username, players):
    """根据人数和我在房间里的位置，返回每个玩家的屏幕位置 (side, index)
    side: top / left / right / bottom
    """
    # 找我在 players 里的索引
    my_idx = next((i for i, p in enumerate(players) if p.username == my_username), 0)
    # 我永远放底部，按顺时针旋转
    # 生成一个顺序列表：从我开始，顺时针：bottom, left(从下往上), top(从左往右), right(从上往下)
    ordered = []
    # 从 我 开始往"左"方向逆时针旋转一圈
    # 简化：我 = 底部；我后面（索引+1）的人按顺时针放到左侧最下面，依次往上，然后到顶部……
    # 但为了简单，我们直接按"上/左/右/下"四个区域分布
    #
    # 计算各区域人数：
    if n == 1:
        areas = {"bottom": 1}
    else:
        rest = n - 1  # 除自己外
        # 先上 1
        top = 1
        rest -= 1
        # 若剩余奇数，上再 +1
        if rest % 2 == 1:
            top += 1
            rest -= 1
        # 剩余平分给左右
        left = rest // 2
        right = rest // 2
        areas = {"top": top, "left": left, "right": right, "bottom": 1}

    # 分配玩家：我在 bottom 中间
    # 其他人按索引顺序（从我之后开始，环绕）填充 top/left/right
    others = [p for p in players if p.username != my_username]
    # 简化：不严格要求位置顺序，只保证数量
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

    # 疲劳每周一 6 点清零
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

    # 我的卡组
    from bonds_data import (
        RELATION_BONDS, REGION_BONDS, POSITION_BONDS, ENEMY_BONDS,
    )
    from game_logic import (
        calc_relation_bonus, calc_region_bonus,
        calc_position_bonus, calc_enemy_bonus,
    )

    decks = BossDeck.query.filter_by(user_id=current_user.id).all()
    my_decks = []
    for d in decks:
        card_ids = json_loads_safe(d.card_ids)
        cards = [CARD_BY_ID.get(cid) for cid in card_ids if CARD_BY_ID.get(cid)]
        dmg = boss_deck_damage_with_bond(cards, today_weak, fatigue) if cards else 0

        # 计算每个类别的加成
        names = [c["name"] for c in cards] if cards else []
        rel = calc_relation_bonus(names) if names else {}
        reg = calc_region_bonus(names) if names else {}
        pos = calc_position_bonus(names) if names else {}
        ene = calc_enemy_bonus(names) if names else {}

        # 找命中的具体羁绊（每类最多一条，即当前生效的那条）
        active_bonds = []  # [{"type": ..., "name": ..., "members": [...], "value": 数字}]

        # 关系类：命中且加成等于 rel 里的值（即最高那个）
        if rel:
            best_val = max(rel.values())
            for bond in RELATION_BONDS:
                hit_bond = None
                for g in bond["groups"]:
                    if all(n in names for n in g) and rel.get(g[0], None) == best_val:
                        hit_bond = {"name": bond["name"], "members": g}
                        break
                if hit_bond:
                    active_bonds.append({
                        "type": "relation",
                        "name": hit_bond["name"],
                        "members": hit_bond["members"],
                        "value": best_val,
                    })
                    break

        # 地域类
        if reg:
            best_val = max(reg.values())
            for bond in REGION_BONDS:
                hit = [n for n in bond["members"] if n in names]
                if len(hit) >= 2 and reg.get(hit[0], None) == best_val:
                    active_bonds.append({
                        "type": "region",
                        "name": bond["name"],
                        "members": hit,
                        "value": best_val,
                    })
                    break

        # 职位类
        if pos:
            best_val = max(pos.values())
            for bond in POSITION_BONDS:
                hit = [n for n in bond["members"] if n in names]
                if len(hit) >= 2 and pos.get(hit[0], None) == best_val:
                    active_bonds.append({
                        "type": "position",
                        "name": bond["name"],
                        "members": hit,
                        "value": best_val,
                    })
                    break

        # 仇敌类
        if ene:
            worst_val = max(ene.values())
            for bond in ENEMY_BONDS:
                for g in bond["groups"]:
                    if all(n in names for n in g) and ene.get(g[0], None) == worst_val:
                        active_bonds.append({
                            "type": "enemy",
                            "name": bond["name"],
                            "members": g,
                            "value": worst_val,
                        })
                        break
                else:
                    continue
                break

        # 给每张卡附加"它自己参与的羁绊"
        for c in cards:
            my_bonds = []
            for b in active_bonds:
                if c["name"] in b["members"]:
                    my_bonds.append(b)
            c["my_bonds"] = my_bonds

        my_decks.append({
            "id": d.id,
            "name": d.name or f"卡组{d.id}",
            "cards": cards,
            "damage": dmg,
            "bonds": active_bonds,  # 卡组级别的（备用）
        })
    
    # 我的伤害记录
    my_dmg = BossDamage.query.filter_by(user_id=current_user.id, week_num=current_week).first()
    my_total_damage = my_dmg.total_damage if my_dmg else 0

    # 本周期排名
    all_records = BossDamage.query.filter_by(week_num=current_week).order_by(BossDamage.total_damage.desc()).all()
    ranks = []
    for idx, r in enumerate(all_records, start=1):
        u = User.query.get(r.user_id)
        if u:
            ranks.append({
                "rank": idx,
                "nickname": u.nickname or u.username,
                "username": u.username,
                "avatar": f"/static/avatars/{u.username}.jpg",
                "damage": r.total_damage,
                "is_me": r.user_id == current_user.id,
            })

    # 出战场次
    today_count = get_today_battle_count(current_user.id)
    remaining = max(0, BOSS_DAILY_LIMIT - today_count)
    active_battle = get_active_battle(current_user.id)

    # 当前出战详情
    active_battle_data = None
    if active_battle:
        card_ids = json_loads_safe(active_battle.card_ids)
        cards = [CARD_BY_ID.get(cid) for cid in card_ids if CARD_BY_ID.get(cid)]
        now = datetime.now()
        total_secs = int((active_battle.ends_at - active_battle.started_at).total_seconds())
        passed = int((now - active_battle.started_at).total_seconds())
        progress = min(100, max(0, int(passed / total_secs * 100))) if total_secs else 100
        is_finished = now >= active_battle.ends_at
        active_battle_data = {
            "id": active_battle.id,
            "cards": cards,
            "progress": progress,
            "is_finished": is_finished,
            "damage": active_battle.damage,
            "started_at": active_battle.started_at.strftime("%H:%M"),
            "ends_at": active_battle.ends_at.strftime("%H:%M"),
        }

    # 下周撤退时间
    next_week = get_next_week_start()
    retreat_str = f"{next_week.month}月{next_week.day}日6时撤退"

    return render_template('world_boss.html',
                           boss={"name": wb.boss_name, "troop": wb.boss_troop},
                           hp_current=wb.current_hp,
                           hp_max=wb.max_hp,
                           hp_percent=max(0, int(wb.current_hp / wb.max_hp * 100)) if wb.max_hp else 0,
                           today_weak=today_weak,
                           today_weak_cn=today_weak_cn,
                           today_color=today_color,
                           retreat_str=retreat_str,
                           killed=wb.current_hp <= 0,
                           cards=owned,
                           fatigue=fatigue,
                           decks=my_decks,
                           my_total_damage=my_total_damage,
                           ranks=ranks,
                           today_count=today_count,
                           remaining=remaining,
                           active_battle=active_battle_data)

@app.route('/world_boss/picker')
@login_required
def world_boss_picker():
    """全屏选卡界面"""
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

    return render_template('world_boss_picker.html',
                           cards=owned,
                           selected_ids=selected_ids,
                           deck_id=deck_id or "",
                           deck_name=deck_name)

@app.route('/world_boss/deck/new', methods=['POST'])
@login_required
def world_boss_deck_new():
    """点新建卡组：检查上限，返回默认名，不实际创建（创建交给 picker 提交）"""
    count = BossDeck.query.filter_by(user_id=current_user.id).count()
    if count >= 20:
        return jsonify({"error": "最多 20 个卡组"}), 400
    default_name = f"卡组{count + 1}"
    return jsonify({"success": True, "name": default_name})

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
    """点出战：创建 BossBattle，快照卡组、算好伤害、2 小时后可收兵"""
    deck_id = request.json.get('deck_id')
    d = BossDeck.query.filter_by(id=deck_id, user_id=current_user.id).first()
    if not d:
        return jsonify({"error": "卡组不存在"}), 404

    # 同时只能一支队伍
    active = get_active_battle(current_user.id)
    if active:
        return jsonify({"error": "已有队伍出战中"}), 400

    # 今日次数
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
        user_id=current_user.id,
        week_num=wb.week_num,
        deck_id=d.id,
        card_ids=json_dumps_safe(card_ids),
        damage=damage,
        started_at=now,
        ends_at=now + timedelta(hours=BOSS_BATTLE_DURATION_HOURS),
        finished=False,
    )
    db.session.add(battle)

    # 疲劳立即 +1（出战那一刻就算）
    for c in cards:
        cid = str(c["id"])
        fatigue[cid] = fatigue.get(cid, 0) + 1
    current_user.set_boss_fatigue(fatigue)

    db.session.commit()
    return jsonify({"success": True, "battle_id": battle.id, "damage": damage})

@app.route('/world_boss/finish', methods=['POST'])
@login_required
def world_boss_finish():
    """收兵：结算伤害、扣 Boss 血、删除出战记录"""
    battle_id = request.json.get('battle_id')
    b = BossBattle.query.filter_by(id=battle_id, user_id=current_user.id, finished=False).first()
    if not b:
        return jsonify({"error": "出战记录不存在"}), 404

    now = datetime.now()
    if now < b.ends_at:
        return jsonify({"error": "还没到时间"}), 400

    wb = ensure_world_boss()

    # 扣 Boss 血
    if wb.current_hp > 0:
        wb.current_hp = max(0, wb.current_hp - b.damage)
        if wb.current_hp == 0 and wb.killed_at is None:
            wb.killed_at = datetime.now()

    # 玩家本周总伤害
    record = BossDamage.query.filter_by(user_id=current_user.id, week_num=wb.week_num).first()
    if not record:
        record = BossDamage(user_id=current_user.id, week_num=wb.week_num, total_damage=0)
        db.session.add(record)
    record.total_damage += b.damage
    record.last_hit_at = now

    # 删除出战记录
    db.session.delete(b)
    db.session.commit()

    return jsonify({
        "success": True,
        "damage": b.damage,
        "hp_current": wb.current_hp,
        "hp_max": wb.max_hp,
        "killed": wb.current_hp <= 0,
    })

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

# ========== 修改密码 ==========
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

# ========== 上传头像 ==========
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
            u.collection_migrated = True
            u.silver = 0
            u.copper = 0
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
    ]
    
    try:
        with db.engine.begin() as conn:
            for sql in migration_sql:
                conn.execute(text(sql))
        print("✅ DB migration done")
    except Exception as e:
        print("⚠️ DB migration error:", e)

    # 一次性清理：删除所有空卡组（card_ids 为空数组的）
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
