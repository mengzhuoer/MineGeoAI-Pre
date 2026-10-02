# -*- coding: utf-8 -*-
# 矿地智预 MineGeoAI-Pre · by zhuoer mengzhuoda · 9.20
"""矿地智预 · 本地知识库检索（RAG 的检索端）

为什么不用向量库：
  · 系统主打离线可用，嵌入模型是又一份几百 MB 的下载，且引入 numpy 之外的新依赖；
  · 知识库规模只有几十到几百节，中文用「字符二元组 + IDF 加权」检索精度已经够用；
  · 纯标准库实现，结果确定、可解释（能指出命中了哪一节），适合答辩讲清"检索是怎么工作的"。

知识库放在 backend/data/kb/*.md，按 `## 标题` 切节；用户可继续追加文件与新节。
若日后要升级为向量检索，只需替换 search() 的实现，调用方不变。
"""
import math
import os
import re

KB_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "kb")

_cache = {"mtime": None, "docs": None}


def _clean(text: str) -> str:
    return re.sub(r"[^\u4e00-\u9fa5A-Za-z0-9]+", "", text or "").lower()


def _grams(text: str) -> list:
    """字符二元组：中文无需分词即可获得稳定的检索特征"""
    s = _clean(text)
    if len(s) < 2:
        return [s] if s else []
    return [s[i:i + 2] for i in range(len(s) - 1)]


def _load():
    """读取知识库（按目录 mtime 缓存，改文件后自动重载）"""
    if not os.path.isdir(KB_DIR):
        return []
    files = sorted(f for f in os.listdir(KB_DIR) if f.lower().endswith((".md", ".txt")))
    stamp = tuple((f, os.path.getmtime(os.path.join(KB_DIR, f))) for f in files)
    if _cache["mtime"] == stamp and _cache["docs"] is not None:
        return _cache["docs"]

    docs = []
    for fn in files:
        try:
            with open(os.path.join(KB_DIR, fn), encoding="utf-8") as f:
                text = f.read()
        except Exception:
            continue
        parts = re.split(r"^##\s+", text, flags=re.M)
        for p in parts[1:]:
            lines = p.strip().splitlines()
            if not lines:
                continue
            title = lines[0].strip()
            body = "\n".join(lines[1:]).strip()
            if len(body) < 20:
                continue
            docs.append({"title": title, "body": body, "source": fn,
                         "grams": _grams(title + " " + body), "title_grams": _grams(title)})
    _cache["mtime"], _cache["docs"] = stamp, docs
    return docs


def stats() -> dict:
    docs = _load()
    files = sorted({d["source"] for d in docs})
    chars = sum(len(d["body"]) for d in docs)
    return {"sections": len(docs), "files": files, "chars": chars}


def search(query: str, k: int = 3, min_score: float = 0.0):
    """检索最相关的知识节，返回 [{title, body, source, score}]"""
    docs = _load()
    q = _grams(query)
    if not docs or not q:
        return []
    n = len(docs)
    df = {}
    for d in docs:
        for g in set(d["grams"]):
            df[g] = df.get(g, 0) + 1

    qset = {}
    for g in q:
        qset[g] = qset.get(g, 0) + 1

    scored = []
    for d in docs:
        body_set = set(d["grams"])
        title_set = set(d["title_grams"])
        s = 0.0
        for g, cnt in qset.items():
            if g in body_set:
                idf = math.log(1 + n / (1 + df.get(g, 0)))
                s += idf * (1 + math.log(cnt))
                if g in title_set:          # 标题命中额外加权
                    s += idf * 1.5
        if s > 0:
            s /= math.sqrt(len(d["grams"]) / 60.0 + 1.0)   # 长度归一，避免偏袒长节
            scored.append({**{kk: d[kk] for kk in ("title", "body", "source")},
                           "score": round(s, 3)})
    scored.sort(key=lambda x: -x["score"])
    out = [d for d in scored[:k] if d["score"] > min_score]
    return out


def context_for(query: str, k: int = 3, max_chars: int = 1200) -> str:
    """把检索到的知识拼成给模型的上下文片段（超长自动截断）"""
    hits = search(query, k=k)
    if not hits:
        return ""
    blocks, total = [], 0
    for h in hits:
        body = h["body"]
        if total + len(body) > max_chars:
            body = body[:max(0, max_chars - total)] + "…"
        blocks.append("【%s】%s" % (h["title"], body))
        total += len(body)
        if total >= max_chars:
            break
    return "\n".join(blocks)
