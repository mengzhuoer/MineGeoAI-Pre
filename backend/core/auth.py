# -*- coding: utf-8 -*-
# 矿地智预 MineGeoAI-Pre · by zhuoer mengzhuoda · 9.20
"""矿地智预 - 本地账号认证服务（SaaS 离线模式）

软件全部部署在本地，认证由本地服务完成（离线可用）：
- SQLite 存储账号，PBKDF2-SHA256 加盐哈希，不存明文
- HMAC-SHA256 签名 Token（默认 7 天有效），纯标准库实现
- 首次启动自动创建超级账号 admin / 123（离线应急超级管理员）
- 未来上云时，将本模块替换为云端认证服务同一接口即可，前端零改动
"""
import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import time

try:
    from . import database as db   # 统一用户数据库
except ImportError:                 # 直接脚本调用时
    import database as db

CORE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = db.DATA_DIR
SECRET_PATH = os.path.join(DATA_DIR, "auth_secret.key")
TOKEN_TTL = 7 * 24 * 3600


def _hash(pwd: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac("sha256", pwd.encode(), bytes.fromhex(salt), 120_000).hex()


def init_db():
    """确保超级账号存在（users 表由统一数据库创建并自动迁移）"""
    os.makedirs(DATA_DIR, exist_ok=True)
    with db.conn() as c:
        if not c.execute("SELECT 1 FROM users WHERE username='admin'").fetchone():
            salt = secrets.token_hex(16)
            c.execute(
                "INSERT INTO users VALUES('admin','super',?,?,datetime('now'))",
                (salt, _hash("123", salt)),
            )
    if not os.path.exists(SECRET_PATH):
        with open(SECRET_PATH, "wb") as f:
            f.write(secrets.token_hex(32).encode())


def create_user(username: str, password: str, role: str = "standard"):
    """创建标准用户（超级管理员调用）"""
    if not re.fullmatch(r"[A-Za-z0-9_\u4e00-\u9fa5-]{2,20}", username):
        raise ValueError("用户名须为 2-20 位字母/数字/中文/下划线/连字符")
    if len(password) < 4:
        raise ValueError("密码至少 4 位")
    if role not in ("standard", "super"):
        role = "standard"
    salt = secrets.token_hex(16)
    try:
        db.create_user(username, password, role, salt=salt, pwd_hash=_hash(password, salt))
    except sqlite3.IntegrityError:
        raise ValueError("用户名已存在")
    return {"username": username, "role": role}


def _secret() -> bytes:
    with open(SECRET_PATH, "rb") as f:
        return f.read()


def verify_login(username: str, password: str):
    """校验账号密码 → 用户信息 或 None"""
    with db.conn() as c:
        row = c.execute(
            "SELECT role, salt, hash FROM users WHERE username=?", (username,)
        ).fetchone()
    if not row:
        return None
    role, salt, h = row
    if hmac.compare_digest(_hash(password, salt), h):
        return {"username": username, "role": role}
    return None


def issue_token(user: dict) -> str:
    payload = base64.urlsafe_b64encode(
        json.dumps({
            "u": user["username"],
            "r": user["role"],
            "exp": int(time.time()) + TOKEN_TTL,
        }).encode()
    ).rstrip(b"=")
    sig = base64.urlsafe_b64encode(
        hmac.new(_secret(), payload, hashlib.sha256).digest()
    ).rstrip(b"=")
    return (payload + b"." + sig).decode()


def verify_token(token: str):
    """校验 Token → 用户信息 或 None"""
    try:
        p, s = token.encode().split(b".")
        expect = base64.urlsafe_b64encode(
            hmac.new(_secret(), p, hashlib.sha256).digest()
        ).rstrip(b"=")
        if not hmac.compare_digest(s, expect):
            return None
        data = json.loads(base64.urlsafe_b64decode(p + b"=" * (-len(p) % 4)))
        if data.get("exp", 0) < time.time():
            return None
        return {"username": data["u"], "role": data["r"]}
    except Exception:
        return None


def list_users():
    with db.conn() as c:
        rows = c.execute("SELECT username, role, created FROM users ORDER BY username").fetchall()
    return [{"username": u, "role": r, "created": t} for u, r, t in rows]


# ---------------- 在线会话追踪（控制中心"在线用户"） ----------------
import threading

_sessions: dict = {}          # token指纹 -> 最近活跃时间戳
_sess_lock = threading.Lock()
ONLINE_WINDOW = 5 * 60        # 5 分钟内活跃视为在线


def touch_session(token: str, username: str):
    fp = hashlib.sha256(token.encode()).hexdigest()[:16]
    with _sess_lock:
        _sessions[fp] = {"ts": time.time(), "username": username}


def online_users() -> list:
    """当前在线的用户名（ONLINE_WINDOW 内有过活动的会话）"""
    cut = time.time() - ONLINE_WINDOW
    with _sess_lock:
        return sorted({v["username"] for v in _sessions.values() if v["ts"] >= cut})


def count_online() -> int:
    cut = time.time() - ONLINE_WINDOW
    with _sess_lock:
        for k in [k for k, v in _sessions.items() if v["ts"] < cut]:
            _sessions.pop(k, None)
        return len(_sessions)


init_db()
