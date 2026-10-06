# models.py
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
import json

db = SQLAlchemy()

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    nickname = db.Column(db.String(50), default="")
    password_hash = db.Column(db.String(255), nullable=False)

    # 货币
    gold = db.Column(db.Integer, default=0)
    silver = db.Column(db.Integer, default=0)
    copper = db.Column(db.Integer, default=0)

    # 收藏
    collection = db.Column(db.Text, default="{}")

    # 建筑
    buildings = db.Column(db.Text, default="{}")
    building_cards = db.Column(db.Text, default="{}")
    deputies = db.Column(db.Text, default="{}")
    materials = db.Column(db.Integer, default=0)

    # 挑战
    challenge_level = db.Column(db.Integer, default=1)
    daily_challenge_wins = db.Column(db.Integer, default=0)

    # 搏卡
    score = db.Column(db.Integer, default=0)
    monthly_score = db.Column(db.Integer, default=0)
    boka_champion_months = db.Column(db.Text, default="[]")

    # 搏卡历史最高
    boka_best_score = db.Column(db.Integer, default=0)
    boka_best_time = db.Column(db.String(20), default="")

    # 世界 Boss 历史最高
    boss_best_damage = db.Column(db.Integer, default=0)
    boss_best_time = db.Column(db.String(20), default="")

    # 新号
    got_starter = db.Column(db.Boolean, default=False)

    # 头像
    avatar = db.Column(db.String(255), default="")
    last_avatar_change = db.Column(db.DateTime, nullable=True)

    # 最后收取时间
    last_collect = db.Column(db.DateTime, nullable=True)

    # 世界 Boss 疲劳值
    boss_fatigue = db.Column(db.Text, default="{}")
    boss_fatigue_reset = db.Column(db.Date, nullable=True)

    # 世界 Boss 血量
    boss_week = db.Column(db.Integer, default=1)
    boss_hp_current = db.Column(db.Integer, default=300000)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def get_collection(self):
        return json.loads(self.collection or "{}")

    def set_collection(self, data):
        self.collection = json.dumps(data)

    def get_buildings(self):
        return json.loads(self.buildings or "{}")

    def set_buildings(self, data):
        self.buildings = json.dumps(data)

    def get_building_cards(self):
        return json.loads(self.building_cards or "{}")

    def set_building_cards(self, data):
        self.building_cards = json.dumps(data)

    def get_deputies(self):
        return json.loads(self.deputies or "{}")

    def set_deputies(self, data):
        self.deputies = json.dumps(data)

    def get_champion_months(self):
        return json.loads(self.boka_champion_months or "[]")

    def set_champion_months(self, data):
        self.boka_champion_months = json.dumps(data)

    def get_boss_fatigue(self):
        return json.loads(self.boss_fatigue or "{}")

    def set_boss_fatigue(self, data):
        self.boss_fatigue = json.dumps(data)
