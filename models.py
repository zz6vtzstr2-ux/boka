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
    collection_migrated = db.Column(db.Boolean, default=False)

    # 建筑
    buildings = db.Column(db.Text, default="{}")
    building_cards = db.Column(db.Text, default="{}")
    deputies = db.Column(db.Text, default="{}")
    materials = db.Column(db.Integer, default=0)
    building_last_collect = db.Column(db.Text, default="{}")

    # 挑战
    challenge_level = db.Column(db.Integer, default=1)
    daily_challenge_wins = db.Column(db.Integer, default=0)
    challenge_deck = db.Column(db.Text, default="[]")
    challenge_wins_total = db.Column(db.Integer, default=0)
    challenge_losses_total = db.Column(db.Integer, default=0)
    challenge_today_wins = db.Column(db.Integer, default=0)
    challenge_today_reset = db.Column(db.Date, nullable=True)
    challenge_active_game = db.Column(db.Text, default="")

    # 搏卡
    score = db.Column(db.Integer, default=0)
    max_score = db.Column(db.Integer, default=0)
    monthly_score = db.Column(db.Integer, default=0)
    boka_champion_months = db.Column(db.Text, default="[]")
    boka_room_id = db.Column(db.Integer, nullable=True)
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
    boss_fatigue_week = db.Column(db.Integer, default=0)

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

    def get_building_last_collect(self):
        return json.loads(self.building_last_collect or "{}")

    def set_building_last_collect(self, data):
        self.building_last_collect = json.dumps(data)

    def get_champion_months(self):
        return json.loads(self.boka_champion_months or "[]")

    def set_champion_months(self, data):
        self.boka_champion_months = json.dumps(data)

    def get_boss_fatigue(self):
        return json.loads(self.boss_fatigue or "{}")

    def set_boss_fatigue(self, data):
        self.boss_fatigue = json.dumps(data)


class ClassCollection(db.Model):
    """班级收藏册：每张卡只保留最早捐献的一条记录"""
    __tablename__ = "class_collection"

    id = db.Column(db.Integer, primary_key=True)
    card_id = db.Column(db.Integer, unique=True, nullable=False)
    donor_username = db.Column(db.String(50), nullable=False)
    donated_at = db.Column(db.DateTime, nullable=False)


class WorldBoss(db.Model):
    """全服共享的世界 Boss 状态，永远只有 1 行（id=1）"""
    __tablename__ = "world_boss"

    id = db.Column(db.Integer, primary_key=True)
    week_num = db.Column(db.Integer, nullable=False, default=1)
    boss_name = db.Column(db.String(50), nullable=False)
    boss_troop = db.Column(db.String(50), nullable=False)
    max_hp = db.Column(db.Integer, nullable=False)
    current_hp = db.Column(db.Integer, nullable=False)
    weak_schedule = db.Column(db.Text, default="[]")
    started_at = db.Column(db.DateTime, nullable=True)
    killed_at = db.Column(db.DateTime, nullable=True)
    payout_done = db.Column(db.Boolean, default=False)


class BossDeck(db.Model):
    """玩家的 Boss 卡组，每人最多 20 个"""
    __tablename__ = "boss_deck"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    name = db.Column(db.String(50), default="")
    card_ids = db.Column(db.Text, default="[]")
    created_at = db.Column(db.DateTime, nullable=True)


class BossDamage(db.Model):
    """玩家每周对 Boss 造成的总伤害"""
    __tablename__ = "boss_damage"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    week_num = db.Column(db.Integer, nullable=False)
    total_damage = db.Column(db.Integer, default=0)
    last_hit_at = db.Column(db.DateTime, nullable=True)

    __table_args__ = (
        db.UniqueConstraint("user_id", "week_num", name="uq_boss_damage_user_week"),
    )


class BossBattle(db.Model):
    """世界 Boss 出战记录：每次出战一条，2 小时后可收兵"""
    __tablename__ = "boss_battle"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    week_num = db.Column(db.Integer, nullable=False)
    deck_id = db.Column(db.Integer, nullable=True)
    card_ids = db.Column(db.Text, default="[]")
    damage = db.Column(db.Integer, default=0)
    started_at = db.Column(db.DateTime, nullable=False)
    ends_at = db.Column(db.DateTime, nullable=False)
    finished = db.Column(db.Boolean, default=False)


class BokaRoom(db.Model):
    """搏卡房间"""
    __tablename__ = "boka_room"

    id = db.Column(db.Integer, primary_key=True)
    room_code = db.Column(db.String(10), unique=True, nullable=False)
    owner_username = db.Column(db.String(50), nullable=False)
    status = db.Column(db.String(20), default="waiting")
    max_players = db.Column(db.Integer, default=14)
    created_at = db.Column(db.DateTime, nullable=True)
    started_at = db.Column(db.DateTime, nullable=True)


class BokaPlayer(db.Model):
    """搏卡房间成员"""
    __tablename__ = "boka_player"

    id = db.Column(db.Integer, primary_key=True)
    room_id = db.Column(db.Integer, db.ForeignKey("boka_room.id"), nullable=False)
    username = db.Column(db.String(50), nullable=False)
    nickname = db.Column(db.String(50), default="")
    ready = db.Column(db.Boolean, default=False)
    seat = db.Column(db.Integer, default=0)
    is_temporary_away = db.Column(db.Boolean, default=False)
    joined_at = db.Column(db.DateTime, nullable=True)


class BokaGame(db.Model):
    __tablename__ = "boka_game"

    id = db.Column(db.Integer, primary_key=True)
    room_id = db.Column(db.Integer, db.ForeignKey("boka_room.id"), nullable=False)
    round_no = db.Column(db.Integer, default=0)
    phase = db.Column(db.String(20), default="waiting")
    card_pool = db.Column(db.Text, default="[]")
    winner_card_id = db.Column(db.Integer, nullable=True)
    winner_username = db.Column(db.String(50), nullable=True)
    created_at = db.Column(db.DateTime, nullable=True)
    finished_at = db.Column(db.DateTime, nullable=True)
    history = db.Column(db.Text, default="[]")
    revealed_at = db.Column(db.DateTime, nullable=True)
    round_winner_card_id = db.Column(db.Integer, nullable=True)
    beauty_left = db.Column(db.Integer, default=3)


class BokaGamePlayer(db.Model):
    """搏卡一局中的玩家状态"""
    __tablename__ = "boka_game_player"

    id = db.Column(db.Integer, primary_key=True)
    game_id = db.Column(db.Integer, db.ForeignKey("boka_game.id"), nullable=False)
    username = db.Column(db.String(50), nullable=False)
    nickname = db.Column(db.String(50), default="")
    hand = db.Column(db.Text, default="[]")
    ready_card = db.Column(db.Text, default="[]")
    locked = db.Column(db.Boolean, default=False)
    rank = db.Column(db.Integer, nullable=True)
    score_change = db.Column(db.Integer, default=0)
    finished_order = db.Column(db.Integer, nullable=True)
    surrendered = db.Column(db.Boolean, default=False)
    surrendered_rank = db.Column(db.Integer, nullable=True)
    beauty_used = db.Column(db.Integer, default=0)


class BokaGameRecord(db.Model):
    """搏卡战绩历史"""
    __tablename__ = "boka_game_record"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), nullable=False)
    game_id = db.Column(db.Integer, nullable=True)
    room_code = db.Column(db.String(10), nullable=True)
    rank = db.Column(db.Integer, nullable=True)
    player_count = db.Column(db.Integer, default=0)
    score_before = db.Column(db.Integer, default=0)
    score_change = db.Column(db.Integer, default=0)
    score_after = db.Column(db.Integer, default=0)
    played_at = db.Column(db.DateTime, nullable=True)
