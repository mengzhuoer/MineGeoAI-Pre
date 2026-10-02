# -*- coding: utf-8 -*-
# 矿地智预 MineGeoAI-Pre · by zhuoer mengzhuoda · 9.20
"""矿地智预 · AI 助手（矿区业务优先，通用闲聊也能接）

设计要点：
  · 数据接地——当前数据集的关键统计由程序算出后注入对话上下文，模型只负责组织语言，
    不让模型凭记忆讲数字；
  · 数字核对——回答里的数字逐个与上下文比对，核对不上的单独列出（前端提示"待核"），
    而不是硬说它错了；
  · 跳转能力——模型在回答末尾输出 [[goto:页面id|按钮文字]] 标记，解析成前端可点的跳转按钮，
    正文里不留标记；
  · 本地模型优先（core/llm.py 统一推理层），未就绪时给出明确原因而不是报错崩溃。
"""
import re

from . import change, geo, kb, llm, predict

# 可供跳转的页面（与前端 APPS 的 id 一致）
PAGES = {
    "home": "系统概览", "data": "数据管理", "preprocess": "数据预处理",
    "classify": "分类分析", "change": "变化分析", "predict": "预测建模",
    "detect": "图像检测", "files": "文件管理", "report": "报告生成",
    "settings": "系统设置",
}

# 小模型格式不稳定：有时写双方括号 [[goto:x|文字]]，有时写成单方括号 [goto:x|文字]，
# 一律接受；id 也允许 change_matrix 这类写法，由 _match_page 归一。
_GOTO_RE = re.compile(r"\[{1,2}\s*goto\s*:\s*([A-Za-z0-9_-]+)\s*(?:\|\s*([^\]\[]+))?\s*\]{1,2}")


def _match_page(pid: str) -> str:
    """把模型写的页面标识归一到已知页面：change_matrix / change-page → change"""
    pid = (pid or "").lower().strip()
    if pid in PAGES:
        return pid
    for k in PAGES:
        if k in pid:
            return k
    return ""

SYSTEM = """你是「矿地智预 MineGeoAI-Pre」系统的 AI 助手，名叫「图图」，服务于矿区土地利用与生态修复业务。

【自称】被问名字或需要指代自己时，用「图图」，不要自称"AI 助手"。

【业务优先】问题若涉及矿区、土地利用、遥感、生态修复或本系统的使用，请结合下方【当前数据】给出专业、具体、可执行的说法。
【通用闲聊】与业务无关的问题也可以正常回答，简短友好即可，并自然地引回矿区业务话题。
【知识库】回答专业问题时，优先依据下方【知识库摘录】的内容，可用自己的话组织；摘录里没有的专业结论不要编造，可以说"知识库里没有这条，建议查阅专业文献"。
【数字纪律】只能引用【当前数据】中出现的数字。数据里没有的，就说明"系统里没有这个数据"，并指出可以在哪个页面查看，绝不虚构或推算。
【跳转能力】回答涉及某个功能页面时，在正文之后另起一行输出跳转标记，格式严格为：[[goto:页面id|按钮文字]]
  可用页面：{pages}
  最多 2 个标记；不需要跳转就不要输出标记；标记不要写在正文中间。
【格式】中文回答，控制在 250 字以内，不要使用 Markdown 标题符号（#、*）与代码块。"""


def _fmt(n, nd=1):
    return ("{:." + str(nd) + "f}").format(n)


def dataset_context() -> str:
    """当前数据集的事实清单（全部由程序计算，模型只引用）"""
    try:
        meta = geo.dataset_meta()
    except Exception:
        return "（当前没有可用的数据集）"
    years = geo.years()
    st = {y: {c["name"]: c["area_ha"] for c in geo.area_stats(geo.load_landuse(y))["classes"]}
          for y in years}
    last = years[-1]
    lines = [
        "【当前数据】矿区：%s；面积 %s 平方公里；分辨率 %s 米；数据年份 %s" % (
            meta.get("region", geo.get_dataset()), meta.get("area_km2"),
            meta.get("resolution_m"), "、".join(str(y) for y in years)),
        "地类体系：%s" % "、".join(c["name"] for c in geo.CLASS_META),
        "%s 年各地类面积（公顷）：%s" % (
            last, "、".join("%s %.1f" % (k, v) for k, v in st[last].items())),
    ]
    chg = None
    try:
        chg = change.analyze(years[0], last)
        dyn = {d["name"]: d for d in chg["dynamics"]}
        lines.append("%s—%s 变化：变化像元占比 %s%%；%s 净变化 %.1f 公顷（年均 %s%%）；"
                     "%s 净变化 %.1f 公顷（年均 %s%%）" % (
                         years[0], last, chg["changed_percent"],
                         "耕地", dyn["耕地"]["change_ha"], dyn["耕地"]["annual_rate_pct"],
                         "建设用地", dyn["建设用地"]["change_ha"], dyn["建设用地"]["annual_rate_pct"]))
        if chg["transfers"]:
            t = chg["transfers"][0]
            lines.append("最主要转移：%s→%s %s 公顷" % (t["from"], t["to"], t["area_ha"]))
        lines.append("变化热点：%d 处" % len(chg["hotspots"]))
    except Exception:
        pass
    try:
        cmp_ = predict.compare_scenarios(years[0], last, last + 10)
        parts = []
        for s in cmp_:
            a = s.get("areas") or s.get("final_areas") or {}
            if a:
                parts.append("%s：耕地 %s、林地 %s、建设用地 %s、采矿用地 %s 公顷" % (
                    s.get("name", s.get("scenario")), _fmt(a.get("耕地", 0)),
                    _fmt(a.get("林地", 0)), _fmt(a.get("建设用地", 0)), _fmt(a.get("采矿用地", 0))))
        if parts:
            lines.append("%d 年多情景预测：%s" % (last + 10, "；".join(parts)))
    except Exception:
        pass
    try:
        v = predict.validate((years[0], years[1]), years[2], "natural")
        lines.append("精度验证：总体精度 %s%%，Kappa %s" % (v["overall_accuracy"], v["kappa"]))
    except Exception:
        pass
    lines.append("可用页面：%s" % "、".join("%s(%s)" % (v, k) for k, v in PAGES.items()))
    return "\n".join(lines)


def _numbers(text: str):
    out = []
    for m in re.finditer(r"-?\d+(?:\.\d+)?", text or ""):
        try:
            out.append(float(m.group(0)))
        except ValueError:
            pass
    return out


def audit(answer: str, context: str) -> list:
    """核对回答里的数字：返回上下文里核对不上的数字（字符串形式，供前端提示）"""
    allowed = _numbers(context)
    bad = []
    for n in _numbers(answer):
        if n in (0.0, 1.0) or abs(n) <= 12:      # 年份、序号、页数等小整数不算
            continue
        ok = any(abs(n - a) <= max(abs(a) * 0.005, 0.05) for a in allowed)
        if not ok:
            bad.append(("%g" % n))
    return bad[:6]


def parse_actions(answer: str):
    """从回答里取出跳转标记，返回 (干净正文, [{id,label}])"""
    acts = []
    for m in _GOTO_RE.finditer(answer or ""):
        pid = _match_page(m.group(1))
        if pid:
            acts.append({"id": pid, "label": (m.group(2) or PAGES[pid]).strip()})
    clean = _GOTO_RE.sub("", answer or "")
    clean = re.sub(r"\[+\s*goto\s*:[^\]]*\]*", "", clean)     # 兜底：清掉任何形状的残留标记
    clean = re.sub(r"\n{3,}", "\n\n", clean).strip()
    seen, uniq = set(), []
    for a in acts:
        if a["id"] not in seen:
            seen.add(a["id"])
            uniq.append(a)
    return clean, uniq[:2]


# 规则兜底：实测 1.5B 给跳转标记不稳定（三轮中一轮），还会把"转移矩阵"说成在系统设置页。
# 这类事实性路由交给程序判断，与模型标记合并（模型优先，程序补齐）。
_ROUTE_RULES = (
    ("change", ("转移矩阵", "变化分析", "变化检测", "动态度", "热点", "转出", "转入")),
    ("classify", ("分类分析", "随机森林", "SVM", "KNN", "混淆矩阵", "制图精度", "用户精度")),
    ("predict", ("预测", "情景", "kappa", "Kappa", "精度验证", "总体精度", "Markov", "CLUE", "2030", "目标年")),
    ("preprocess", ("预处理", "辐射定标", "大气校正", "去云", "去噪")),
    ("detect", ("图像检测", "导入影像", "上传影像", "扰动检测")),
    ("report", ("报告生成", "生成报告", "Word", "PDF", "导出报告")),
    ("data", ("数据集", "切换矿区", "数据管理", "多矿区")),
    ("files", ("文件管理", "上传文件", "配额", "存储空间")),
    ("settings", ("系统设置", "主题", "壁纸", "图标风格", "个性化")),
)


def route(question: str) -> str:
    """按关键词判断问题该去哪个页面（程序判断，比小模型可靠）"""
    q = question or ""
    for pid, keys in _ROUTE_RULES:
        if any(k in q for k in keys):
            return pid
    return ""


def ask(question: str, history=None) -> dict:
    """一次问答。未就绪时抛 llm.LLMError（消息可直接给用户看）"""
    question = (question or "").strip()
    if not question:
        raise llm.LLMError("请先输入问题")
    ctx = dataset_context()
    hits = kb.search(question, k=3)
    kb_ctx = "\n".join("【%s】%s" % (h["title"], h["body"]) for h in hits)
    sysmsg = (SYSTEM.format(pages="、".join("%s(%s)" % (v, k) for k, v in PAGES.items()))
              + "\n\n" + ctx
              + ("\n\n【知识库摘录】（可引用，不必逐字照抄）\n" + kb_ctx if kb_ctx else ""))
    msgs = [{"role": "system", "content": sysmsg}]
    for h in (history or [])[-6:]:
        role = "assistant" if h.get("role") == "assistant" else "user"
        if h.get("content"):
            msgs.append({"role": role, "content": str(h["content"])[:1000]})
    msgs.append({"role": "user", "content": question})

    r = llm.chat(msgs)
    clean, actions = parse_actions(r["text"])
    # 规则优先：实测模型给的页面常错（问报告生成却指向文件管理），规则按关键词判断更可靠；
    # 规则判不出来时才采用模型自己的标记。
    rid = route(question)
    if rid:
        label = actions[0]["label"] if (actions and actions[0]["id"] == rid) else ("打开" + PAGES[rid])
        actions = [{"id": rid, "label": label}]
        if "打开" not in label and PAGES.get(rid) not in label:
            actions[0]["label"] = "打开" + PAGES[rid]
    r["answer"] = clean
    r["actions"] = actions
    r["unverified"] = audit(clean, ctx)
    r["references"] = [h["title"] for h in hits]
    r.pop("text", None)
    return r
