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
    building_output, total_output, calc_combo_stats, calc_score_change
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

@app.route('/')
@login_required
def game():
    return render_template('game.html', username=current_user.username)

@app.route('/draw', methods=['POST'])
@login_required
def draw():
    free = request.json.get('free', False)
    today = date.today()
    if current_user.last_free_reset != today:
        current_user.daily_free_used = False
        current_user.last_free_reset = today
    if free:
        if current_user.daily_free_used:
            return jsonify({"error": "今日免费抽卡已用完"}), 400
        current_user.daily_free_used = True
    cards, result_type = draw_card()
    if result_type == "empty":
        db.session.commit()
        return jsonify({"type": "empty", "message": "厂商忘放卡了"})
    collection = current_user.get_collection()
    for card in cards:
        cid = str(card["id"])
        collection[cid] = collection.get(cid, 0) + 1
    current_user.set_collection(collection)
    db.session.commit()
    if result_type == "double":
        return jsonify({"type": "double", "cards": cards, "message": "双黄蛋"})
    return jsonify({"type": "normal", "cards": cards})

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
    return render_template('collection.html', cards=cards_with_count, all_cards=CARDS)

@app.route('/buildings')
@login_required
def buildings():
    buildings_data = current_user.get_buildings()
    building_cards = current_user.get_building_cards()
    deputies = current_user.get_deputies()
    result = []
    for bid, attr in ATTR_MAP.items():
        level = buildings_data.get(str(bid), 0)
        card_id = building_cards.get(str(bid))
        card = CARD_BY_ID.get(card_id) if card_id else None
        dep_id = deputies.get(str(bid))
        dep_card = CARD_BY_ID.get(dep_id) if dep_id else None
        result.append({"bid": bid, "name": ATTR_NAMES[bid], "attr": attr,
                       "level": level, "card": card, "deputy": dep_card})
    return render_template('buildings.html', buildings=result, materials=current_user.materials)

@app.route('/collect', methods=['POST'])
@login_required
def collect():
    buildings_data = current_user.get_buildings()
    building_cards = current_user.get_building_cards()
    deputies = current_user.get_deputies()
    output = total_output(buildings_data, building_cards, deputies)
    copper = int(output * 8)
    silver = copper // 100
    gold = silver // 100
    copper = copper % 100
    silver = silver % 100
    current_user.last_collect = datetime.now()
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

@app.route('/challenge')
@login_required
def challenge():
    return render_template('challenge.html', level=current_user.challenge_level)

@app.route('/challenge/start', methods=['POST'])
@login_required
def challenge_start():
    level = current_user.challenge_level
    ai_cards = random.sample(CARDS, 6)
    return jsonify({"ai_cards": ai_cards, "level": level})

@app.route('/challenge/result', methods=['POST'])
@login_required
def challenge_result():
    win = request.json.get('win', False)
    if win:
        current_user.challenge_level += 1
        level = current_user.challenge_level
        base = 30
        tier = min(level // 50, 9)
        coef = 1.0 + tier * 0.2
        materials = round(base * coef)
        current_user.materials += materials
        db.session.commit()
        return jsonify({"success": True, "materials": materials, "new_level": current_user.challenge_level})
    return jsonify({"success": False})

@app.route('/boka')
@login_required
def boka():
    return render_template('boka.html')

@app.route('/boka/create', methods=['POST'])
@login_required
def boka_create():
    room_id = random.randint(1000, 9999)
    return jsonify({"room_id": room_id})

with app.app_context():
    db.create_all()

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=int(os.getenv('PORT', 5000)))
