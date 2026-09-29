# models.py
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
import json

db = SQLAlchemy()

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    score = db.Column(db.Integer, default=0)
    collection = db.Column(db.Text, default="{}")
    buildings = db.Column(db.Text, default="{}")
    building_cards = db.Column(db.Text, default="{}")
    deputies = db.Column(db.Text, default="{}")
    challenge_level = db.Column(db.Integer, default=1)
    daily_free_used = db.Column(db.Boolean, default=False)
    last_free_reset = db.Column(db.Date, nullable=True)
    last_collect = db.Column(db.DateTime, nullable=True)
    materials = db.Column(db.Integer, default=0)

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
