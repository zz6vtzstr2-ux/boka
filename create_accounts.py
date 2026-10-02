# create_accounts.py
from app import app
from models import db, User

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

with app.app_context():
    db.create_all()
    for username, password, nickname in ACCOUNTS:
        if User.query.filter_by(username=username).first():
            print(f"跳过已存在：{username}")
            continue
        u = User(username=username, nickname=nickname)
        u.set_password(password)
        db.session.add(u)
        print(f"已创建：{username} / {password} / {nickname}")
    db.session.commit()
