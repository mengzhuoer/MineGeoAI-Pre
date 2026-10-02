# -*- coding: utf-8 -*-
# 矿地智预 MineGeoAI-Pre · by zhuoer mengzhuoda · 9.20
"""矿地智预 - 标准化报告生成引擎 v2

Word（docx）：规范封面 · 目录 · 执行摘要 · 图表题编号 · 页眉页脚页码 · 样式化表格
PDF：matplotlib 多页排版（离线可用，无外部依赖）
报告内容按模板自动整合：分类成果 / 变化分析 / 多情景预测 / 精度验证 / 面积趋势图
"""
import io
import os
import time

import numpy as np
from docx import Document
from docx.enum.section import WD_SECTION
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor
from PIL import Image

from . import change, classify, geo, predict

REPORT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "reports")

# 官方报告配色（与公文体系一致）
INK = RGBColor(0x26, 0x32, 0x29)
MUTED = RGBColor(0x66, 0x71, 0x6A)
GREEN = RGBColor(0x2F, 0x6B, 0x4F)
GREEN_D = RGBColor(0x1F, 0x4A, 0x37)
HEADER_FILL = "2F6B4F"
ZEBRA_FILL = "F2F5F0"

TEMPLATES = {
    "comprehensive": {
        "name": "矿区土地利用变化分析综合报告",
        "sections": ["overview", "method", "classification", "change", "prediction", "accuracy", "conclusion"],
    },
    "change": {
        "name": "矿区土地利用变化分析报告",
        "sections": ["overview", "method", "change", "conclusion"],
    },
    "prediction": {
        "name": "生态修复规划支撑报告（多情景预测）",
        "sections": ["overview", "method", "prediction", "accuracy", "conclusion"],
    },
    "monitor": {
        "name": "矿区土地利用动态监测报告",
        "sections": ["overview", "classification", "change", "conclusion"],
    },
    "restoration": {
        "name": "生态修复效果评估报告",
        "sections": ["overview", "change", "prediction", "conclusion"],
    },
    "compliance": {
        "name": "矿山合规监管数据报告",
        "sections": ["overview", "classification", "change", "accuracy", "conclusion"],
    },
    "planning": {
        "name": "矿区开采规划支撑报告",
        "sections": ["overview", "prediction", "accuracy", "conclusion"],
    },
    "research": {
        "name": "矿区土地变化科学研究数据报告",
        "sections": ["overview", "method", "classification", "change", "prediction", "accuracy", "conclusion"],
    },
}


# ================================================================
# 图表绘制（matplotlib，中文字体）
# ================================================================
def _mpl():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib import font_manager
    if "chinese_font_ready" not in _mpl.__dict__:
        for fp in (r"C:\Windows\Fonts\msyh.ttc", r"C:\Windows\Fonts\simhei.ttf"):
            try:
                font_manager.fontManager.addfont(fp)
                plt.rcParams["font.family"] = font_manager.FontProperties(fname=fp).get_name()
                _mpl.chinese_font_ready = True
                break
            except Exception:
                continue
        plt.rcParams["axes.unicode_minus"] = False
    return matplotlib.pyplot


def _fig_png(fig) -> bytes:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=130, bbox_inches="tight", facecolor="white")
    _mpl().close(fig)
    return buf.getvalue()


def trend_chart(meta: dict) -> bytes:
    """各地类面积时序堆叠图"""
    plt = _mpl()
    years = [str(y) for y in meta["years"]]
    cls = [c["name"] for c in meta["classes"]]
    colors = [c["color"] for c in meta["classes"]]
    hist = meta["history"]
    data = [[hist[y][n] for y in years] for n in cls]
    fig, ax = plt.subplots(figsize=(7.6, 3.6))
    ax.stackplot(years, *data, labels=cls, colors=colors, alpha=0.92)
    ax.set_ylabel("面积 (公顷)")
    ax.legend(loc="upper left", bbox_to_anchor=(1.01, 1.0), fontsize=8)
    ax.set_title("各地类面积时序变化", fontsize=12)
    ax.tick_params(labelsize=9)
    return _fig_png(fig)


def scenario_chart(cmp: list, target_year: int) -> bytes:
    """四情景关键地类面积对比图"""
    plt = _mpl()
    names = [s["scenario_name"] for s in cmp]
    kinds = ["采矿用地", "林地", "耕地"]
    colors = ["#e74c3c", "#3e8e41", "#f0c850"]
    x = np.arange(len(names))
    fig, ax = plt.subplots(figsize=(7.6, 3.4))
    w = 0.26
    for i, (k, c) in enumerate(zip(kinds, colors)):
        vals = [s["final_areas"].get(k, 0) for s in cmp]
        ax.bar(x + (i - 1) * w, vals, width=w, label=k, color=c, alpha=0.9)
    ax.set_xticks(x)
    ax.set_xticklabels(names, fontsize=10)
    ax.set_ylabel("面积 (公顷)")
    ax.legend(fontsize=9)
    ax.set_title(f"{target_year} 年多情景关键地类面积对比", fontsize=12)
    ax.tick_params(labelsize=9)
    return _fig_png(fig)


# ================================================================
# Word 文档辅助
# ================================================================
def _set_font(run, size=10.5, bold=False, color=None, name="Times New Roman", east="宋体"):
    run.font.size = Pt(size)
    run.font.bold = bold
    run.font.name = name
    run._element.rPr.rFonts.set(qn("w:eastAsia"), east)
    if color:
        run.font.color.rgb = color


def _heading(doc, text, level=1):
    p = doc.add_heading("", level=level)
    run = p.add_run(text)
    _set_font(run, size=15 if level == 1 else 12.5, bold=True, color=GREEN_D, east="黑体")
    p.paragraph_format.space_before = Pt(14)
    p.paragraph_format.space_after = Pt(8)
    return p


def _para(doc, text, size=10.5, bold=False, align=None, color=None, indent=True):
    p = doc.add_paragraph()
    if align:
        p.alignment = align
    p.paragraph_format.line_spacing = 1.4
    if indent and align is None:
        p.paragraph_format.first_line_indent = Pt(size * 2)
    run = p.add_run(text)
    _set_font(run, size=size, bold=bold, color=color)
    return p


def _shade(cell, fill):
    tcPr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:fill"), fill)
    tcPr.append(shd)


def _table(doc, headers, rows, zebra=True):
    t = doc.add_table(rows=1 + len(rows), cols=len(headers))
    t.style = "Table Grid"
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    for j, h in enumerate(headers):
        cell = t.rows[0].cells[j]
        cell.text = ""
        run = cell.paragraphs[0].add_run(str(h))
        _set_font(run, size=9.5, bold=True, color=RGBColor(0xFF, 0xFF, 0xFF))
        cell.paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.CENTER
        _shade(cell, HEADER_FILL)
    for i, row in enumerate(rows):
        for j, v in enumerate(row):
            cell = t.rows[i + 1].cells[j]
            cell.text = ""
            run = cell.paragraphs[0].add_run(str(v))
            _set_font(run, size=9.5)
            if j > 0:
                cell.paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.CENTER
            if zebra and i % 2 == 1:
                _shade(cell, ZEBRA_FILL)
    return t


def _image(doc, png_bytes, width_cm=14.2):
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.add_run().add_picture(io.BytesIO(png_bytes), width=Cm(width_cm))
    return p


def _caption(doc, text):
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_after = Pt(10)
    run = p.add_run(text)
    _set_font(run, size=9, color=MUTED)
    return p


def _field(paragraph, instr, hint=""):
    run = paragraph.add_run()
    b = OxmlElement("w:fldChar"); b.set(qn("w:fldCharType"), "begin")
    it = OxmlElement("w:instrText"); it.set(qn("xml:space"), "preserve"); it.text = instr
    s = OxmlElement("w:fldChar"); s.set(qn("w:fldCharType"), "separate")
    t = OxmlElement("w:t"); t.text = hint
    e = OxmlElement("w:fldChar"); e.set(qn("w:fldCharType"), "end")
    run._r.append(b); run._r.append(it); run._r.append(s); run._r.append(t); run._r.append(e)
    return run


def _add_toc(doc):
    p = doc.add_paragraph()
    p.paragraph_format.space_after = Pt(6)
    _field(p, 'TOC \\o "1-3" \\h \\z \\u', "（在 Word 中右键此处 → 更新域，可生成目录页码）")
    _para(doc, "", size=8)


def _add_footer(doc, report_name):
    section = doc.sections[0]
    footer = section.footer
    p = footer.paragraphs[0]
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = p.add_run("矿地智预 MineGeoAI-Pre · " + report_name + "    第 ")
    _set_font(run, size=8.5, color=MUTED)
    _field(p, "PAGE", "1")
    run2 = p.add_run(" 页")
    _set_font(run2, size=8.5, color=MUTED)
    # 页眉
    hp = section.header.paragraphs[0]
    hp.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    run3 = hp.add_run("矿地智预 MineGeoAI-Pre 智慧地矿软件系统")
    _set_font(run3, size=8.5, color=MUTED)


# ================================================================
# 数据准备
# ================================================================
def _collect(options):
    a = int(options.get("a_year", 2000))
    b = int(options.get("b_year", 2020))
    target = int(options.get("target_year", 2030))
    scenario = options.get("scenario", "natural")
    algo = options.get("algorithm", "rf")
    meta = geo.dataset_meta()
    cls = classify.classify(b, algo, 0.35)
    chg = change.analyze(a, b)
    pred = predict.run_ca_markov(a, b, target, scenario)
    val = predict.validate((2000, 2005), 2010, scenario)
    cmp = predict.compare_scenarios(a, b, target)
    return meta, cls, chg, pred, val, cmp, a, b, target, scenario


def _docx_name(tpl):
    return f"矿地智预报告_{tpl['name']}_{time.strftime('%Y%m%d_%H%M%S')}.docx"


def _pdf_name(tpl):
    return f"矿地智预报告_{tpl['name']}_{time.strftime('%Y%m%d_%H%M%S')}.pdf"


# ================================================================
# Word 生成
# ================================================================
def generate_docx(template: str, options: dict) -> str:
    tpl = TEMPLATES[template]
    meta, cls, chg, pred, val, cmp, a, b, target, scenario = _collect(options)

    doc = Document()
    sec = doc.sections[0]
    sec.top_margin = Cm(2.4)
    sec.bottom_margin = Cm(2.4)
    sec.left_margin = Cm(2.6)
    sec.right_margin = Cm(2.6)
    _add_footer(doc, tpl["name"])

    # ---------- 封面 ----------
    for _ in range(5):
        doc.add_paragraph()
    p = doc.add_paragraph(); p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    _set_font(p.add_run("矿 地 智 预"), size=30, bold=True, color=GREEN_D, east="黑体")
    p = doc.add_paragraph(); p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    _set_font(p.add_run("MineGeoAI-Pre"), size=13, color=MUTED)
    p = doc.add_paragraph(); p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_before = Pt(26)
    _set_font(p.add_run(tpl["name"]), size=20, bold=True, color=INK, east="黑体")
    p = doc.add_paragraph(); p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_before = Pt(10)
    _set_font(p.add_run(f"—— {meta['region']}"), size=13, color=INK)
    for _ in range(4):
        doc.add_paragraph()
    for line in [
        f"数据源：Landsat 时序遥感影像（{a}—{b}） · {meta['crs']} · {meta['resolution_m']} m",
        f"研究区面积：{meta['area_km2']} km² · 共 {len(meta['years'])} 期",
        f"报告类型：{tpl['name']}",
    ]:
        p = doc.add_paragraph(); p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        _set_font(p.add_run(line), size=10.5, color=MUTED)
    for _ in range(4):
        doc.add_paragraph()
    p = doc.add_paragraph(); p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    _set_font(p.add_run("编制单位：矿地智预科技有限公司"), size=12, bold=True, color=INK)
    p = doc.add_paragraph(); p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    _set_font(p.add_run(f"编制日期：{time.strftime('%Y年%m月%d日')}"), size=10.5, color=MUTED)
    doc.add_page_break()

    # ---------- 目录 ----------
    _heading(doc, "目  录", 1)
    _add_toc(doc)
    doc.add_page_break()

    # ---------- 执行摘要 ----------
    _heading(doc, "执行摘要", 1)
    top1 = chg["transfers"][0] if chg["transfers"] else {"from": "—", "to": "—", "area_ha": 0}
    _para(doc, f"本研究基于 {a}—{b} 年 {len(meta['years'])} 期 Landsat 时序遥感数据与改良 "
               f"CLUE-S + CA-Markov 融合模型，完成{meta['region']}土地利用现状分类、"
               f"时空变化分析与{target}年多情景空间格局预测。主要结论如下：")
    _para(doc, f"（1）分类精度：{cls['algorithm_name']}总体精度 {cls['overall_accuracy']}%，"
               f"Kappa 系数 {cls['kappa']}；", bold=False)
    _para(doc, f"（2）变化特征：{a}—{b} 年 {chg['changed_percent']}% 的像元发生地类转换，"
               f"最主要转换方向为「{top1['from']} → {top1['to']}」（{top1['area_ha']} 公顷）；")
    _para(doc, f"（3）预测验证：模型独立预测精度 Kappa 达 {val['kappa']}，处于高质量模拟水平；")
    _para(doc, f"（4）情景推演：{target} 年「{pred['scenario_name']}」情景下，"
               f"采矿用地 {pred['area_history'][-1]['areas']['采矿用地']:.0f} 公顷、"
               f"林地 {pred['area_history'][-1]['areas']['林地']:.0f} 公顷、"
               f"耕地 {pred['area_history'][-1]['areas']['耕地']:.0f} 公顷。")
    doc.add_page_break()

    # ---------- 正文章节 ----------
    for sec_name in tpl["sections"]:
        if sec_name == "overview":
            _heading(doc, "一、项目概况", 1)
            _para(doc, f"本报告针对{meta['region']}，基于 {a}—{b} 年共 {len(meta['years'])} 期 "
                       f"Landsat 时序遥感影像，开展土地利用现状分类、时空变化分析与{target}年"
                       f"多情景空间格局预测。研究区总面积 {meta['area_km2']} 平方公里，"
                       f"采用 {meta['crs']} 坐标系统，空间分辨率 {meta['resolution_m']} 米。")
            _para(doc, "矿区地处黄土高原，采掘与复垦活动交替进行，土地损毁与生态修复并存。"
                       "本报告成果可为矿区国土空间监管、生态修复规划与开采布局优化提供量化决策依据。")

        elif sec_name == "method":
            _heading(doc, "二、数据与方法", 1)
            _para(doc, "技术路线：遥感数据获取 → 辐射定标 → 大气校正（DOS 暗目标法）→ 去云去噪 → "
                       "特征构建（光谱+纹理+地形）→ 随机森林监督分类 → 变化检测与转移矩阵 → "
                       "CA-Markov 与 CLUE-S 融合模型多情景预测 → 精度验证（Kappa 系数）。")
            _para(doc, "预测模型融合 CLUE-S（驱动因子-土地利用关系解析）与 CA-Markov（数量-空间格局模拟）"
                       "优势：以两期实测土地利用数据标定马尔可夫转移概率矩阵，以 Logistic 回归拟合"
                       "高程、坡度、距道路、距水域、距矿距离五类驱动因子的空间适宜性，"
                       "经元胞自动机按邻域规则完成空间分配，并叠加水域缓冲、生态红线、耕地保护约束。")

        elif sec_name == "classification":
            _heading(doc, f"三、{b} 年土地利用分类结果", 1)
            _para(doc, f"采用{cls['algorithm_name']}对预处理后影像进行监督分类，"
                       f"训练样本 {cls['n_train']} 个、验证样本 {cls['n_test']} 个。"
                       f"总体精度 {cls['overall_accuracy']}%，Kappa 系数 {cls['kappa']}。")
            _image(doc, cls["prediction_map"])
            _caption(doc, f"图 1  {b} 年土地利用分类图")
            stats = geo.area_stats(geo.load_landuse(b))
            _table(doc, ["地类", "面积(公顷)", "占比(%)"],
                   [[c["name"], c["area_ha"], c["percent"]] for c in stats["classes"]])
            _caption(doc, f"表 1  {b} 年各地类面积统计")

        elif sec_name == "change":
            _heading(doc, f"四、{a}—{b} 年土地利用变化分析", 1)
            _para(doc, f"{a}—{b} 年间，研究区共 {chg['changed_percent']}% 的像元发生土地利用类型转换，"
                       "主要转换方向如下表所示。")
            _table(doc, ["转换方向", "面积(公顷)", "占转换比例(%)"],
                   [[t["from"] + " → " + t["to"], t["area_ha"],
                     round(t["pixels"] / max(chg["changed_pixels"], 1) * 100, 1)]
                    for t in chg["transfers"][:8]])
            _caption(doc, "表 2  主要土地利用转移类型")
            _image(doc, trend_chart(meta))
            _caption(doc, "图 2  各地类面积时序变化")
            _image(doc, chg["change_map"])
            _caption(doc, f"图 3  {a}—{b} 年土地利用变化检测图")
            _table(doc, ["地类", f"{a}年(公顷)", f"{b}年(公顷)", "变化(公顷)", "年均动态度(%)"],
                   [[d["name"], d["area_a_ha"], d["area_b_ha"], d["change_ha"], d["annual_rate_pct"]]
                    for d in chg["dynamics"]])
            _caption(doc, "表 3  各地类面积变化与动态度")

        elif sec_name == "prediction":
            _heading(doc, f"五、{target} 年多情景空间格局预测", 1)
            _para(doc, f"以 {a}—{b} 年转移规律为基准，采用 CA-Markov 融合模型，"
                       f"在「{pred['scenario_name']}」情景下对 {target} 年土地利用空间格局进行模拟。")
            last = pred["area_history"][-1]
            base = geo.area_stats(geo.load_landuse(b))
            base_map = {c["name"]: c["area_ha"] for c in base["classes"]}
            _table(doc, ["地类", f"{b}年(公顷)", f"{target}年(公顷)", "变化(公顷)"],
                   [[name, base_map.get(name, 0), area, round(area - base_map.get(name, 0), 1)]
                    for name, area in last["areas"].items()])
            _caption(doc, f"表 4  {target} 年预测面积统计（{pred['scenario_name']}情景）")
            for key, img in pred["images"].items():
                if key == "change":
                    _image(doc, img)
                    _caption(doc, f"图 4  {b}—{target} 年预测变化图")
                else:
                    _image(doc, img)
                    _caption(doc, f"图 5  {key} 年土地利用预测图")
            # 多情景对比
            _heading(doc, "（一）多情景对比分析", 2)
            _para(doc, "为支撑决策，对常规开采、强化开采、生态优先、综合平衡四种发展路径"
                       f"进行了 {target} 年对比推演：")
            _table(doc, ["情景", "采矿用地(ha)", "林地(ha)", "耕地(ha)", "建设用地(ha)"],
                   [[s["scenario_name"], round(s["final_areas"].get("采矿用地", 0), 1),
                     round(s["final_areas"].get("林地", 0), 1), round(s["final_areas"].get("耕地", 0), 1),
                     round(s["final_areas"].get("建设用地", 0), 1)] for s in cmp])
            _caption(doc, f"表 5  {target} 年四情景关键地类面积对比")
            _image(doc, scenario_chart(cmp, target))
            _caption(doc, f"图 6  {target} 年多情景关键地类面积对比图")

        elif sec_name == "accuracy":
            _heading(doc, "六、模型精度验证", 1)
            _para(doc, f"以 {val['train']['a']}—{val['train']['b']} 年数据训练模型、独立预测 "
                       f"{val['target_year']} 年并与实测对比：总体精度 {val['overall_accuracy']}%，"
                       f"Kappa 系数 {val['kappa']}，达到高质量模拟水平（Kappa>0.75）。")
            _table(doc, ["地类", "实测面积(公顷)", "预测面积(公顷)", "误差(%)"],
                   [[e["name"], e["true_ha"], e["pred_ha"], e["err_pct"]] for e in val["area_error"]])
            _caption(doc, f"表 6  {val['target_year']} 年预测面积误差检验")
            _image(doc, val["images"]["predicted"])
            _caption(doc, f"图 7  {val['target_year']} 年预测格局图")
            _image(doc, val["images"]["truth"])
            _caption(doc, f"图 8  {val['target_year']} 年实测格局图")

        elif sec_name == "conclusion":
            _heading(doc, "七、结论与建议", 1)
            top1 = chg["transfers"][0] if chg["transfers"] else {"from": "—", "to": "—"}
            _para(doc, f"（1）研究区 {a}—{b} 年土地利用变化以「{top1['from']} → {top1['to']}」为主导，"
                       "叠加耕地与林地的相互转换、建设用地持续扩张，属典型资源型区域演变模式。")
            _para(doc, f"（2）CA-Markov 与 CLUE-S 融合模型经验证精度可靠（Kappa={val['kappa']}），"
                       f"可用于 {target} 年及更长时序的空间格局推演。")
            eco = next((s for s in cmp if s["scenario"] == "ecological"), None)
            if eco:
                _para(doc, f"（3）多情景对比显示：生态优先情景下采矿用地 "
                           f"{round(eco['final_areas'].get('采矿用地', 0), 1)} 公顷，"
                           "较常规开采情景显著收缩、林草地持续恢复。建议监管与修复规划参照多情景对比结果，"
                           "划定生态红线缓冲区，优先复垦排土场与老采坑积水区，落实耕地占补平衡。")

    # 附注
    _para(doc, "", size=9)
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(14)
    _set_font(p.add_run("附注：本报告由矿地智预智慧地矿软件系统（MineGeoAI-Pre）自动生成。"
                        "如当前数据集为示范数据，则成果仅用于系统演示与教学；"
                        "如为真实数据，其来源与检测方法见数据集元数据。"),
              size=8.5, color=MUTED)

    os.makedirs(REPORT_DIR, exist_ok=True)
    path = os.path.join(REPORT_DIR, _docx_name(tpl))
    doc.save(path)
    return path


# ================================================================
# PDF 生成（matplotlib 多页排版）
# ================================================================
def _wrap_cjk(text, width):
    """按字符宽度折行（CJK 全角计 2，ASCII 计 1）"""
    lines, cur, cur_w = [], "", 0
    for ch in text:
        w = 2 if ord(ch) > 0x2E80 else 1
        if cur_w + w > width and cur:
            lines.append(cur)
            cur, cur_w = ch, w
        else:
            cur += ch
            cur_w += w
    if cur:
        lines.append(cur)
    return lines


def generate_pdf(template: str, options: dict) -> str:
    tpl = TEMPLATES[template]
    meta, cls, chg, pred, val, cmp, a, b, target, scenario = _collect(options)
    plt = _mpl()
    from matplotlib.backends.backend_pdf import PdfPages

    os.makedirs(REPORT_DIR, exist_ok=True)
    path = os.path.join(REPORT_DIR, _pdf_name(tpl))

    pp = PdfPages(path)
    W, H = 8.27, 11.69  # A4 英寸

    def page():
        return plt.figure(figsize=(W, H))

    # ---------- 封面 ----------
    fig = page()
    fig.text(0.5, 0.62, "矿 地 智 预", ha="center", fontsize=34, fontweight="bold", color="#1F4A37")
    fig.text(0.5, 0.575, "MineGeoAI-Pre", ha="center", fontsize=11, color="#66716A")
    fig.text(0.5, 0.48, tpl["name"], ha="center", fontsize=19, fontweight="bold", color="#263229")
    fig.text(0.5, 0.435, f"—— {meta['region']}", ha="center", fontsize=12, color="#263229")
    meta_lines = [
        f"数据源：Landsat 时序遥感影像（{a}—{b}） · {meta['crs']} · {meta['resolution_m']} m",
        f"研究区面积：{meta['area_km2']} km² · 共 {len(meta['years'])} 期",
        f"编制单位：矿地智预科技有限公司",
        f"编制日期：{time.strftime('%Y年%m月%d日')}",
    ]
    for i, line in enumerate(meta_lines):
        fig.text(0.5, 0.26 - i * 0.035, line, ha="center", fontsize=10.5, color="#66716A")
    fig.text(0.5, 0.06, "矿地智预 MineGeoAI-Pre 智慧地矿软件系统", ha="center", fontsize=8, color="#98A099")
    pp.savefig(fig); plt.close(fig)

    # ---------- 内容页排版 ----------
    def section_page(title, paras, table=None, images=(), captions=()):
        fig = page()
        y = 0.935
        fig.text(0.08, 0.955, title, fontsize=15, fontweight="bold", color="#1F4A37")
        for para in paras:
            for line in _wrap_cjk(para, 46):
                if y < 0.10:
                    pp.savefig(fig); plt.close(fig)
                    fig = page(); y = 0.93
                fig.text(0.08, y, line, fontsize=10, color="#3A463E", va="top")
                y -= 0.021
            y -= 0.012
        if table is not None:
            rows = len(table[1]) + 1
            ax = fig.add_axes([0.08, max(0.05, y - rows * 0.032 - 0.06), 0.84, rows * 0.032 + 0.05])
            ax.axis("off")
            ax.table(cellText=table[1], colLabels=table[0], loc="center", cellLoc="center",
                     colColours=["#2F6B4F"] * len(table[0]),
                     colWidths=[0.84 / len(table[0])] * len(table[0]))
            y -= rows * 0.032 + 0.10
        for img, cap in zip(images, captions):
            if y < 0.42:
                pp.savefig(fig); plt.close(fig)
                fig = page(); y = 0.93
            im = np.asarray(Image.open(io.BytesIO(img)))
            ax = fig.add_axes([0.12, max(0.05, y - 0.52), 0.76, 0.46])
            ax.imshow(im)
            ax.axis("off")
            fig.text(0.5, max(0.03, y - 0.56), cap, ha="center", fontsize=9, color="#66716A")
            y -= 0.60
        fig.text(0.5, 0.03, f"矿地智预 MineGeoAI-Pre · {tpl['name']}", ha="center", fontsize=8, color="#98A099")
        pp.savefig(fig); plt.close(fig)

    # 执行摘要
    top1 = chg["transfers"][0] if chg["transfers"] else {"from": "—", "to": "—", "area_ha": 0}
    section_page("执行摘要", [
        f"本研究基于 {a}—{b} 年 Landsat 时序数据与 CLUE-S + CA-Markov 融合模型，"
        f"完成{meta['region']}土地利用分类、变化分析与{target}年多情景预测。主要结论：",
        f"（1）分类精度：总体精度 {cls['overall_accuracy']}%，Kappa 系数 {cls['kappa']}；",
        f"（2）变化特征：{chg['changed_percent']}% 像元发生转换，主导方向「{top1['from']} → {top1['to']}」"
        f"（{top1['area_ha']} 公顷）；",
        f"（3）预测验证：独立预测 Kappa 达 {val['kappa']}；",
        f"（4）{target} 年「{pred['scenario_name']}」情景：采矿用地 "
        f"{pred['area_history'][-1]['areas']['采矿用地']:.0f} 公顷、"
        f"林地 {pred['area_history'][-1]['areas']['林地']:.0f} 公顷。",
    ])

    # 章节
    for sec_name in tpl["sections"]:
        if sec_name == "overview":
            section_page("一、项目概况", [
                f"本报告针对{meta['region']}，基于 {a}—{b} 年共 {len(meta['years'])} 期 Landsat "
                f"时序遥感影像，研究区总面积 {meta['area_km2']} km²，"
                f"{meta['crs']} 坐标系，分辨率 {meta['resolution_m']} m。",
                "矿区地处黄土高原，采掘与复垦交替，成果可为国土空间监管、生态修复规划与开采布局优化提供量化依据。",
            ])
        elif sec_name == "method":
            section_page("二、数据与方法", [
                "技术路线：数据获取 → 辐射定标 → 大气校正 → 去云去噪 → 特征构建 → 随机森林分类 → "
                "变化检测与转移矩阵 → CA-Markov + CLUE-S 多情景预测 → Kappa 精度验证。",
                "模型以两期实测数据标定转移概率矩阵，以 Logistic 回归拟合高程、坡度、距道路、距水域、"
                "距矿距离五类驱动因子，经元胞自动机空间分配，并叠加水域缓冲、生态红线、耕地保护约束。",
            ])
        elif sec_name == "classification":
            stats = geo.area_stats(geo.load_landuse(b))
            section_page(f"三、{b} 年土地利用分类结果", [
                f"采用{cls['algorithm_name']}监督分类，总体精度 {cls['overall_accuracy']}%，"
                f"Kappa {cls['kappa']}（训练 {cls['n_train']} / 验证 {cls['n_test']} 样本）。",
            ],
                table=(["地类", "面积(公顷)", "占比(%)"],
                       [[c["name"], c["area_ha"], c["percent"]] for c in stats["classes"]]),
                images=(cls["prediction_map"],),
                captions=(f"图 1  {b} 年土地利用分类图",))
        elif sec_name == "change":
            section_page(f"四、{a}—{b} 年土地利用变化分析", [
                f"{a}—{b} 年共 {chg['changed_percent']}% 像元发生转换。",
            ],
                table=(["转换方向", "面积(公顷)", "占比(%)"],
                       [[t["from"] + "→" + t["to"], t["area_ha"],
                         round(t["pixels"] / max(chg["changed_pixels"], 1) * 100, 1)]
                        for t in chg["transfers"][:8]]),
                images=(chg["change_map"],),
                captions=(f"图 2  {a}—{b} 年土地利用变化检测图",))
        elif sec_name == "prediction":
            last = pred["area_history"][-1]
            base = geo.area_stats(geo.load_landuse(b))
            base_map = {c["name"]: c["area_ha"] for c in base["classes"]}
            section_page(f"五、{target} 年多情景预测", [
                f"「{pred['scenario_name']}」情景下 {target} 年预测结果如下，四情景对比见表。",
            ],
                table=(["情景", "采矿(ha)", "林地(ha)", "耕地(ha)"],
                       [[s["scenario_name"], round(s["final_areas"].get("采矿用地", 0), 1),
                         round(s["final_areas"].get("林地", 0), 1),
                         round(s["final_areas"].get("耕地", 0), 1)] for s in cmp]),
                images=(pred["images"].get(str(target), pred["images"].get("change", b"")),
                        scenario_chart(cmp, target)),
                captions=(f"图 3  {target} 年预测格局图", f"图 4  四情景对比图"))
        elif sec_name == "accuracy":
            section_page("六、模型精度验证", [
                f"以 {val['train']['a']}—{val['train']['b']} 训练、独立预测 {val['target_year']} 年："
                f"总体精度 {val['overall_accuracy']}%，Kappa {val['kappa']}。",
            ],
                table=(["地类", "实测(ha)", "预测(ha)", "误差(%)"],
                       [[e["name"], e["true_ha"], e["pred_ha"], e["err_pct"]] for e in val["area_error"]]))
        elif sec_name == "conclusion":
            eco = next((s for s in cmp if s["scenario"] == "ecological"), None)
            paras = [
                f"（1）{a}—{b} 年变化以「{top1['from']}→{top1['to']}」为主导，叠加耕地/林地转换与建设用地扩张。",
                f"（2）融合模型验证精度可靠（Kappa={val['kappa']}），可用于中长期推演。",
            ]
            if eco:
                paras.append("（3）生态优先情景下采矿用地显著收缩、林草恢复，建议据此划定红线缓冲区、"
                             "优先复垦排土场与老采坑积水区。")
            section_page("七、结论与建议", paras)

    pp.close()
    return path
