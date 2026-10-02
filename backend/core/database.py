# -*- coding: utf-8 -*-
# 矿地智预 MineGeoAI-Pre · by zhuoer mengzhuoda · 9.20
"""矿地智预 - 统一用户数据库（SQLite + WAL）

所有用户数据集中于此：
  users       账号（含从旧 auth.db 自动迁移）
  user_files  文件索引（磁盘实体在 data/storage/<用户名>/）
  user_prefs  用户偏好（主题/图标/壁纸等，登录时跨设备恢复）
  user_history分析操作历史

配额：标准用户 10 GB，超级管理员 50 GB。
"""
import os
import re
import sqlite3
import uuid
import shutil

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # backend/
DATA_DIR = os.path.join(BASE_DIR, "data")
DB_PATH = os.path.join(DATA_DIR, "minegeoai.db")
LEGACY_AUTH_DB = os.path.join(DATA_DIR, "auth.db")
STORAGE_ROOT = os.path.join(DATA_DIR, "storage")

QUOTA_BYTES = {
    "super": 50 * 1024 ** 3,
    "standard": 10 * 1024 ** 3,
}
DEFAULT_ROLE = "standard"


def conn() -> sqlite3.Connection:
    c = sqlite3.connect(DB_PATH, timeout=15)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA foreign_keys=ON")
    return c


def init_db():
    os.makedirs(DATA_DIR, exist_ok=True)
    os.makedirs(STORAGE_ROOT, exist_ok=True)
    with conn() as c:
        c.execute("PRAGMA journal_mode=WAL")
        c.execute(
            "CREATE TABLE IF NOT EXISTS users("
            "username TEXT PRIMARY KEY, role TEXT, salt TEXT, hash TEXT, created TEXT)"
        )
        c.execute(
            "CREATE TABLE IF NOT EXISTS user_files("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT, folder TEXT DEFAULT '/',"
            "name TEXT, size INTEGER DEFAULT 0, mime TEXT, is_dir INTEGER DEFAULT 0,"
            "disk_name TEXT, created TEXT DEFAULT (datetime('now','localtime')))"
        )
        c.execute(
            "CREATE INDEX IF NOT EXISTS idx_files_user ON user_files(username, folder)"
        )
        c.execute(
            "CREATE TABLE IF NOT EXISTS user_prefs("
            "username TEXT, key TEXT, value TEXT,"
            "PRIMARY KEY (username, key))"
        )
        c.execute(
            "CREATE TABLE IF NOT EXISTS user_history("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT, type TEXT, detail TEXT,"
            "created TEXT DEFAULT (datetime('now','localtime')))"
        )
        _migrate_columns(c)
        _migrate_legacy_users(c)


def _migrate_columns(c):
    """为既有库补齐后加的列（在线编辑引入的修改时间）"""
    cols = {r["name"] for r in c.execute("PRAGMA table_info(user_files)")}
    if "modified" not in cols:
        c.execute("ALTER TABLE user_files ADD COLUMN modified TEXT")


def _migrate_legacy_users(c):
    """旧 auth.db 的账号自动并入统一库"""
    n = c.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    if n > 0 or not os.path.isfile(LEGACY_AUTH_DB):
        return
    try:
        old = sqlite3.connect(LEGACY_AUTH_DB)
        rows = old.execute("SELECT username, role, salt, hash, created FROM users").fetchall()
        for r in rows:
            c.execute("INSERT OR IGNORE INTO users VALUES(?,?,?,?,?)", r)
        old.close()
    except Exception:
        pass


def quota_bytes(role: str) -> int:
    return QUOTA_BYTES.get(role, QUOTA_BYTES[DEFAULT_ROLE])


def used_bytes(username: str) -> int:
    with conn() as c:
        row = c.execute(
            "SELECT COALESCE(SUM(size),0) AS s FROM user_files WHERE username=? AND is_dir=0",
            (username,),
        ).fetchone()
    return int(row["s"])


# ---------------- 用户管理 ----------------
def create_user(username: str, password: str, role: str = DEFAULT_ROLE, salt: str = "", pwd_hash: str = ""):
    with conn() as c:
        c.execute(
            "INSERT INTO users(username, role, salt, hash, created) VALUES(?,?,?,?,datetime('now','localtime'))",
            (username, role, salt, pwd_hash),
        )


def get_user_dir(username: str) -> str:
    d = os.path.join(STORAGE_ROOT, username)
    os.makedirs(d, exist_ok=True)
    return d


# ---------------- 文件管理 ----------------
def safe_folder(folder: str) -> str:
    """规范化文件夹路径，拒绝危险输入。返回以 / 结尾的路径。"""
    if not folder:
        return "/"
    f = folder.replace("\\", "/")
    f = re.sub(r"/+", "/", f)
    if f and not f.startswith("/"):
        f = "/" + f
    if not f.endswith("/"):
        f += "/"
    if ".." in f:
        raise ValueError("路径不合法")
    return f or "/"


def safe_name(name: str) -> str:
    name = os.path.basename(name.replace("\\", "/")).strip()
    if not name or name in (".", "..") or re.search(r'[\\/:*?"<>|]', name):
        raise ValueError("文件名不合法")
    return name[:180]


def list_files(username: str, folder: str):
    folder = safe_folder(folder)
    with conn() as c:
        rows = c.execute(
            "SELECT id, name, size, mime, is_dir, created, modified FROM user_files "
            "WHERE username=? AND folder=? ORDER BY is_dir DESC, name COLLATE NOCASE",
            (username, folder),
        ).fetchall()
    return [dict(r) for r in rows]


def add_file(username: str, folder: str, name: str, size: int, mime: str, disk_name: str) -> int:
    with conn() as c:
        cur = c.execute(
            "INSERT INTO user_files(username, folder, name, size, mime, is_dir, disk_name)"
            " VALUES(?,?,?,?,?,0,?)",
            (username, safe_folder(folder), name, size, mime, disk_name),
        )
        return cur.lastrowid


def add_folder(username: str, folder: str, name: str):
    with conn() as c:
        exists = c.execute(
            "SELECT 1 FROM user_files WHERE username=? AND folder=? AND name=? AND is_dir=1",
            (username, safe_folder(folder), name),
        ).fetchone()
        if exists:
            raise ValueError("同名文件夹已存在")
        c.execute(
            "INSERT INTO user_files(username, folder, name, is_dir) VALUES(?,?,?,1)",
            (username, safe_folder(folder), name),
        )


def get_file(username: str, file_id: int):
    with conn() as c:
        r = c.execute(
            "SELECT * FROM user_files WHERE username=? AND id=? AND is_dir=0",
            (username, file_id),
        ).fetchone()
    return dict(r) if r else None


def delete_file(username: str, file_id: int) -> int:
    """删除文件或文件夹（递归），返回释放的字节数。"""
    with conn() as c:
        row = c.execute(
            "SELECT * FROM user_files WHERE username=? AND id=?", (username, file_id)
        ).fetchone()
        if not row:
            return 0
        freed = 0
        disk_paths = []
        if row["is_dir"]:
            prefix = safe_folder(row["folder"] + row["name"])
            rows = c.execute(
                "SELECT * FROM user_files WHERE username=? AND (folder=? OR folder LIKE ?)",
                (username, prefix, prefix + "%"),
            ).fetchall()
            for r in rows:
                freed += 0 if r["is_dir"] else r["size"]
                if r["disk_name"]:
                    disk_paths.append(os.path.join(get_user_dir(username), r["disk_name"]))
            c.execute(
                "DELETE FROM user_files WHERE username=? AND (folder=? OR folder LIKE ?)",
                (username, prefix, prefix + "%"),
            )
        else:
            freed = row["size"]
            if row["disk_name"]:
                disk_paths.append(os.path.join(get_user_dir(username), row["disk_name"]))
            c.execute("DELETE FROM user_files WHERE id=?", (row["id"],))
    for p in disk_paths:
        try:
            os.remove(p)
        except OSError:
            pass
    return freed


def update_file_content(username: str, file_id: int, size: int) -> str:
    """在线编辑写回后更新索引（大小与修改时间），返回新的修改时间。"""
    with conn() as c:
        c.execute(
            "UPDATE user_files SET size=?, modified=datetime('now','localtime')"
            " WHERE username=? AND id=? AND is_dir=0",
            (size, username, file_id),
        )
        row = c.execute(
            "SELECT modified FROM user_files WHERE username=? AND id=?", (username, file_id)
        ).fetchone()
    return row["modified"] if row else ""


def new_disk_name(orig_name: str) -> str:
    ext = ""
    m = re.search(r"(\.[A-Za-z0-9]{1,8})$", orig_name)
    if m:
        ext = m.group(1)
    return uuid.uuid4().hex[:16] + ext


# ---------------- 偏好与历史 ----------------
def set_pref(username: str, key: str, value: str):
    with conn() as c:
        c.execute(
            "INSERT INTO user_prefs(username, key, value) VALUES(?,?,?) "
            "ON CONFLICT(username, key) DO UPDATE SET value=excluded.value",
            (username, key, value),
        )


def get_prefs(username: str) -> dict:
    with conn() as c:
        rows = c.execute("SELECT key, value FROM user_prefs WHERE username=?", (username,)).fetchall()
    return {r["key"]: r["value"] for r in rows}


def add_history(username: str, htype: str, detail: str):
    with conn() as c:
        c.execute(
            "INSERT INTO user_history(username, type, detail) VALUES(?,?,?)",
            (username, htype, detail[:300]),
        )


def get_history(username: str, limit: int = 10):
    with conn() as c:
        rows = c.execute(
            "SELECT type, detail, created FROM user_history WHERE username=? "
            "ORDER BY id DESC LIMIT ?",
            (username, max(1, min(limit, 50))),
        ).fetchall()
    return [dict(r) for r in rows]


init_db()   # 模块导入即初始化（幂等）
