# -*- coding: utf-8 -*-
# 矿地智预 MineGeoAI-Pre · by zhuoer mengzhuoda · 9.20
"""矿地智预 · 站内消息（用户私聊 + 超级管理员系统通知）

设计要点：
  · 私聊：sender/recipient 都是用户名，`is_read` 记在消息上（一对一只需一个状态）
  · 系统通知：kind='notice'，**对所有账号可见**（不按 recipient 过滤）；
    已读状态按人记录在 user_msg_reads 表——否则一个人读了，别人那里也变成已读
  · 在线状态复用认证模块的内存会话（ONLINE_WINDOW 内活跃即在线），不额外建表
  · 表按需创建（首次访问时 CREATE TABLE IF NOT EXISTS），不依赖启动顺序
  · 单条长度与历史条数都设上限，避免把聊天记录堆成数据库负担
"""
import time

from . import auth, database

BROADCAST = "@all"        # 系统通知的收件人标识（群发给全部账号）
MAX_BODY = 2000           # 单条消息最大字符数
HISTORY_LIMIT = 300       # 单次最多返回的历史条数
THREAD_PREVIEW = 60       # 会话列表里预览的字符数


def _ensure(c):
    """消息表与通知已读表按需创建（幂等）"""
    c.execute(
        "CREATE TABLE IF NOT EXISTS user_messages("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, sender TEXT, recipient TEXT, body TEXT,"
        "kind TEXT DEFAULT 'chat', is_read INTEGER DEFAULT 0,"
        "created TEXT DEFAULT (datetime('now','localtime')))"
    )
    c.execute("CREATE INDEX IF NOT EXISTS idx_msg_to ON user_messages(recipient, is_read)")
    # 系统通知按人记已读：一条通知多人可见，各自独立的状态
    c.execute(
        "CREATE TABLE IF NOT EXISTS user_msg_reads("
        "msg_id INTEGER, username TEXT, PRIMARY KEY(msg_id, username))"
    )


def _usernames() -> list:
    return [u["username"] for u in auth.list_users()]


def online_users() -> list:
    """当前在线用户名（认证模块的会话表里 ONLINE_WINDOW 内活跃的）"""
    try:
        return auth.online_users()
    except Exception:
        return []


def send(sender: str, to: str, body: str, kind: str = "chat") -> dict:
    body = (body or "").strip()[:MAX_BODY]
    to = (to or "").strip()
    if not body:
        raise ValueError("消息内容不能为空")
    if not to:
        raise ValueError("请选择收件人")
    if kind == "notice":
        to = BROADCAST                      # 系统通知统一存 @all，读时按 kind 判定
    elif to == BROADCAST:
        raise ValueError("只有系统通知可以群发")
    elif to not in _usernames():
        raise ValueError("收件人不存在")
    elif to == sender:
        raise ValueError("不能给自己发消息")
    with database.conn() as c:
        _ensure(c)
        cur = c.execute("INSERT INTO user_messages(sender,recipient,body,kind) VALUES(?,?,?,?)",
                        (sender, to, body, kind))
        mid = cur.lastrowid
        row = c.execute("SELECT created FROM user_messages WHERE id=?", (mid,)).fetchone()
    return {"id": mid, "created": row["created"] if row else "", "to": to, "kind": kind}


def _notice_unread(c, username: str) -> int:
    """该用户未读的系统通知数（按人独立统计）"""
    return int(c.execute(
        "SELECT COUNT(*) FROM user_messages m WHERE m.kind='notice'"
        " AND NOT EXISTS (SELECT 1 FROM user_msg_reads r WHERE r.msg_id=m.id AND r.username=?)",
        (username,)).fetchone()[0])


def threads(username: str) -> list:
    """会话列表：系统通知（对所有账号常驻）+ 与其他账号的会话"""
    online = set(online_users())
    out = []
    with database.conn() as c:
        _ensure(c)
        # 系统通知：不按收件人过滤，所有账号都能看到
        n = _notice_unread(c, username)
        last = c.execute("SELECT body,created FROM user_messages WHERE kind='notice'"
                         " ORDER BY id DESC LIMIT 1").fetchone()
        if n or last:
            out.append({
                "peer": BROADCAST, "name": "系统通知", "notice": True, "online": True,
                "unread": n,
                "last": (last["body"][:THREAD_PREVIEW] if last else ""),
                "time": (last["created"] if last else ""),
            })
        # 一对一会话
        for u in _usernames():
            if u == username:
                continue
            n = c.execute(
                "SELECT COUNT(*) FROM user_messages WHERE sender=? AND recipient=? AND is_read=0",
                (u, username)).fetchone()[0]
            last = c.execute(
                "SELECT sender,body,created FROM user_messages"
                " WHERE (sender=? AND recipient=?) OR (sender=? AND recipient=?)"
                " ORDER BY id DESC LIMIT 1", (u, username, username, u)).fetchone()
            if not last and not n:
                continue
            body = last["body"] if last else ""
            out.append({
                "peer": u, "name": u, "notice": False, "online": u in online,
                "unread": int(n),
                "last": (("我：" if last and last["sender"] == username else "") + body[:THREAD_PREVIEW]),
                "time": (last["created"] if last else ""),
            })
    out.sort(key=lambda x: (not x["notice"], -x["unread"], x["time"]), reverse=False)
    out.sort(key=lambda x: x["time"], reverse=True)
    # 系统通知常驻最前
    out.sort(key=lambda x: (not x["notice"],))
    return out


def thread(username: str, peer: str, mark_read: bool = True) -> list:
    """取与某个 peer 的对话（默认同时标记为已读）"""
    peer = (peer or "").strip()
    if peer != BROADCAST and peer not in _usernames():
        raise ValueError("会话不存在")
    with database.conn() as c:
        _ensure(c)
        if peer == BROADCAST:
            rows = c.execute(
                "SELECT id,sender,recipient,body,kind,is_read,created FROM user_messages"
                " WHERE kind='notice' ORDER BY id DESC LIMIT ?", (HISTORY_LIMIT,)).fetchall()
            if mark_read:                       # 按人记已读，不影响其他人的未读状态
                for r in rows:
                    c.execute("INSERT OR IGNORE INTO user_msg_reads(msg_id,username) VALUES(?,?)",
                              (r["id"], username))
        else:
            rows = c.execute(
                "SELECT id,sender,recipient,body,kind,is_read,created FROM user_messages"
                " WHERE (sender=? AND recipient=?) OR (sender=? AND recipient=?)"
                " ORDER BY id DESC LIMIT ?", (peer, username, username, peer, HISTORY_LIMIT)).fetchall()
            if mark_read:
                c.execute("UPDATE user_messages SET is_read=1 WHERE sender=? AND recipient=?",
                          (peer, username))
    items = [dict(r) for r in rows]
    items.reverse()
    for it in items:
        it["mine"] = (it["sender"] == username)
    return items


def unread_total(username: str) -> int:
    """未读总数 = 未读私聊 + 未读系统通知（Dock 角标用）"""
    with database.conn() as c:
        _ensure(c)
        chats = int(c.execute("SELECT COUNT(*) FROM user_messages"
                              " WHERE recipient=? AND kind='chat' AND is_read=0",
                              (username,)).fetchone()[0])
        return chats + _notice_unread(c, username)


def directory(username: str) -> list:
    """可对话的账号列表（含在线状态），供"发起对话"用"""
    online = set(online_users())
    return [{"username": u["username"], "role": u.get("role", ""),
             "role_label": role_label(u.get("role", "")), "online": u["username"] in online}
            for u in auth.list_users() if u["username"] != username]


# ---------------- 联系人搜索 ----------------

# 角色中文名：系统里实际用的是 super / standard（见 auth.create_user），其余为兼容旧值
ROLE_LABEL = {"super": "超级管理员", "standard": "标准用户",
              "admin": "管理员", "user": "普通用户", "guest": "访客"}
SEARCH_LIMIT = 20         # 每类结果最多返回条数
SNIPPET_PAD = 24          # 消息命中片段前后各留的字符数


def role_label(role: str) -> str:
    """角色标识转中文（未知角色原样返回）"""
    return ROLE_LABEL.get(role or "", role or "")


def _like(q: str) -> str:
    """转成 LIKE 模式串：转义 \\ % _ 三个特殊字符，避免用户输入被当通配符"""
    esc = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return "%" + esc + "%"


def _snippet(body: str, q: str) -> str:
    """截取命中位置附近的一段正文（命中在开头时不留前省略号）"""
    i = (body or "").lower().find((q or "").lower())
    if i < 0:
        return (body or "")[:SNIPPET_PAD * 2]
    a, b = max(0, i - SNIPPET_PAD), min(len(body), i + len(q) + SNIPPET_PAD)
    return ("…" if a > 0 else "") + body[a:b] + ("…" if b < len(body) else "")


def search(username: str, q: str, limit: int = SEARCH_LIMIT) -> dict:
    """搜索联系人（账号 / 角色）与消息内容

    contacts —— 账号目录里匹配的：**含尚未建立会话的账号**，可直接开聊；
                排序为 在线 > 有未读 > 已有会话 > 名称
    messages —— 我参与的消息（含系统通知）正文里匹配的，带命中片段，点击跳到该会话
    """
    q = (q or "").strip()[:64]
    if not q:
        return {"query": "", "contacts": [], "messages": []}
    needle = q.lower()
    seen = {t["peer"]: t for t in threads(username)}      # 已有会话带着未读数和预览
    contacts = []
    for u in directory(username):
        name, role = u["username"], u.get("role", "")
        label = role_label(role)
        if needle not in name.lower() and needle not in label.lower():
            continue
        t = seen.get(name, {})
        contacts.append({
            "username": name, "name": name, "role": role, "role_label": label,
            "online": bool(u.get("online")),
            "has_thread": name in seen,
            "unread": int(t.get("unread", 0)),
            "last": t.get("last", ""), "time": t.get("time", ""),
        })
    contacts.sort(key=lambda x: (not x["online"], -x["unread"], not x["has_thread"], x["name"]))
    with database.conn() as c:
        _ensure(c)
        rows = c.execute(
            "SELECT id,sender,recipient,body,kind,created FROM user_messages"
            " WHERE body LIKE ? ESCAPE '\\'"
            "   AND ((kind='chat' AND (sender=? OR recipient=?)) OR kind='notice')"
            " ORDER BY id DESC LIMIT ?", (_like(q), username, username, limit)).fetchall()
    messages = []
    for r in rows:
        notice = r["kind"] == "notice"
        peer = BROADCAST if notice else (r["recipient"] if r["sender"] == username else r["sender"])
        messages.append({
            "id": r["id"], "peer": peer, "name": "系统通知" if notice else peer,
            "notice": notice, "mine": r["sender"] == username, "sender": r["sender"],
            "snippet": _snippet(r["body"], q), "created": r["created"],
        })
    return {"query": q, "contacts": contacts[:limit], "messages": messages}
