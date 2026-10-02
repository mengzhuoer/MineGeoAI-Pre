# -*- coding: utf-8 -*-
# 矿地智预 MineGeoAI-Pre · by zhuoer mengzhuoda · 9.20
"""矿地智预 - 变化检测与分析引擎

多期土地利用变化：转移矩阵、动态度、变化热点、逐类变化速率、驱动关联
"""
import numpy as np
from scipy import ndimage

from . import geo


def analyze(a_year: int, b_year: int):
    """数据库两期土地利用对比"""
    return analyze_arrays(geo.load_landuse(a_year), geo.load_landuse(b_year),
                          a_year, b_year, span=max(b_year - a_year, 1))


def analyze_arrays(A, B, name_a="前期", name_b="后期", span: int = 1):
    """两幅地类栅格的变化分析（导入影像与数据库对比也走这里）

    name_a / name_b 为分析对象名（年份，或"导入影像"这类说明），仅用于展示。
    """
    A = np.asarray(A)
    B = np.asarray(B)
    if A.shape != B.shape:
        raise ValueError(f"两幅栅格尺寸不一致：{A.shape} vs {B.shape}")
    a_year, b_year = name_a, name_b

    m = geo.transition_matrix(A, B)
    total = A.size
    pixel_ha = 900.0 / 10000.0

    # 转移概率矩阵（行归一化）+ 平滑避免 0 概率
    prob = m / np.maximum(m.sum(axis=1, keepdims=True), 1)
    prob = np.clip(prob, 1e-4, None)
    prob /= prob.sum(axis=1, keepdims=True)

    # 基准期某地类一个像元都没有时，行归一化会退化成均匀分布（1/6），
    # 看上去像"同概率转为各地类"的假数据（真实数据集的采矿用地就属此类），
    # 故置空并在前端标注"无数据"
    empty_rows = [i for i in range(len(geo.CLASS_META)) if int(m[i].sum()) == 0]
    prob_list = [
        [None] * len(geo.CLASS_META) if i in empty_rows
        else [round(float(v), 4) for v in prob[i]]
        for i in range(len(geo.CLASS_META))
    ]

    rows = []
    for i, from_m in enumerate(geo.CLASS_META):
        for j, to_m in enumerate(geo.CLASS_META):
            n = int(m[i, j])
            if i == j or n == 0:
                continue
            rows.append({
                "from": from_m["name"], "to": to_m["name"],
                "pixels": n, "area_ha": round(n * pixel_ha, 1),
                "prob": round(float(prob[i, j]), 4),
            })
    rows.sort(key=lambda r: -r["pixels"])

    # 动态度 K = (Ub-Ua)/Ua / T * 100%
    dynamics = []
    stats_a = {c["name"]: int((A == c["id"]).sum()) for c in geo.CLASS_META}
    stats_b = {c["name"]: int((B == c["id"]).sum()) for c in geo.CLASS_META}
    for meta in geo.CLASS_META:
        ua, ub = stats_a[meta["name"]], stats_b[meta["name"]]
        # 基准期为 0 时增长率无定义（除以 0 会得到几百 % 的假值），置空显示"—"
        k = None if ua == 0 else round((ub - ua) / ua / span * 100.0, 2)
        dynamics.append({
            **meta,
            "area_a_ha": round(ua * pixel_ha, 1),
            "area_b_ha": round(ub * pixel_ha, 1),
            "change_ha": round((ub - ua) * pixel_ha, 1),
            "annual_rate_pct": k,
            "new_in_period": ua == 0 and ub > 0,
        })

    changed = (A != B)
    # 变化热点：变化密度核密度（高斯平滑）
    density = ndimage.gaussian_filter(changed.astype(np.float32), sigma=4)
    hotspots = []
    hot = (density > np.quantile(density[density > 0.08], 0.75)) if (density > 0.08).any() else np.zeros_like(density, bool)
    lab, nlab = ndimage.label(hot)
    for r in range(1, nlab + 1):
        size = int((lab == r).sum())
        if size < 12:
            continue
        ys, xs = np.where(lab == r)
        hotspots.append({
            "id": r,
            "center_px": [int(xs.mean()), int(ys.mean())],
            "pixels": size,
            "intensity": round(float(density[ys, xs].mean()), 3),
        })
    hotspots.sort(key=lambda h_: -h_["pixels"])
    hotspots = hotspots[:8]

    shade = geo.hillshade(geo.load_driver("dem"))
    change_map = geo.render_change_png(A, B, shade)

    return {
        "a_year": a_year, "b_year": b_year,
        "changed_pixels": int(changed.sum()),
        "changed_percent": round(changed.mean() * 100, 2),
        "matrix": m.tolist(),
        "prob_matrix": prob_list,
        "empty_classes": [geo.CLASS_META[i]["name"] for i in empty_rows],
        "transfers": rows[:20],
        "dynamics": dynamics,
        "hotspots": hotspots,
        "change_map": change_map,
    }
