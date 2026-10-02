# -*- coding: utf-8 -*-
# 矿地智预 MineGeoAI-Pre · by zhuoer mengzhuoda · 9.20
"""矿地智预 - 多情景预测引擎（CA-Markov + CLUE-S 融合）

== 方法体系 ==

1. Markov 数量预测模块
   由两期真实土地利用数据计算转移概率矩阵 P（行归一化），
   矩阵分数幂实现任意年限外推：P(Δt) = P^(Δt/T)，需求面积 = 基准分布 · P^(Δt)。

2. 情景修正模块
   12 项可调参数以乘性因子作用于转移矩阵列向量，行归一化保持随机性。

3. CLUE-S 适宜性模块（真实标定）
   以两期间实际发生变化的像元为样本、驱动因子(DEM/坡度/距路/距水/距矿)为特征，
   逐类型拟合 Logistic 回归 → 每类地物的空间适宜性概率面（跨类 softmax 归一）。

4. CA 空间分配模块
   转换势 = wT·P(当前→目标) + wN·邻域密度 + wS·适宜性 + 交通牵引；
   按需求缺口逐年迭代分配，5×5 邻域聚合；
   水域缓冲/生态红线/耕地保护为空间硬约束。

5. CLUE-S 独立模式
   需求模块 = 历史面积线性趋势外推 + 情景系数；空间分配 = 适宜性排序 + 转换弹性。
"""
import numpy as np
from scipy import ndimage
from scipy.linalg import fractional_matrix_power
from sklearn.linear_model import LogisticRegression

from . import geo

# ---------------------------------------------------------------- 情景预设
SCENARIOS = {
    "natural": {
        "name": "常规开采", "desc": "延续历史趋势的自然发展情景",
        "params": {
            "miningIntensity": 0.55, "restorationRate": 0.25, "policyConstraint": 0.35,
            "farmlandProtection": 0.25, "ecoRedline": 0.30, "waterProtection": 0.45,
            "dumpTreatment": 0.30, "urbanGrowth": 0.45, "forestExpansion": 0.25,
            "transportPull": 0.40, "neighborhoodWeight": 0.45, "suitabilityWeight": 0.40,
        },
    },
    "intensive": {
        "name": "强化开采", "desc": "矿产资源加速开发情景",
        "params": {
            "miningIntensity": 0.90, "restorationRate": 0.05, "policyConstraint": 0.10,
            "farmlandProtection": 0.05, "ecoRedline": 0.10, "waterProtection": 0.30,
            "dumpTreatment": 0.10, "urbanGrowth": 0.60, "forestExpansion": 0.10,
            "transportPull": 0.60, "neighborhoodWeight": 0.60, "suitabilityWeight": 0.30,
        },
    },
    "ecological": {
        "name": "生态优先", "desc": "生态修复优先、矿区恢复治理情景",
        "params": {
            "miningIntensity": 0.20, "restorationRate": 0.85, "policyConstraint": 0.80,
            "farmlandProtection": 0.55, "ecoRedline": 0.85, "waterProtection": 0.85,
            "dumpTreatment": 0.75, "urbanGrowth": 0.15, "forestExpansion": 0.70,
            "transportPull": 0.20, "neighborhoodWeight": 0.40, "suitabilityWeight": 0.55,
        },
    },
    "balanced": {
        "name": "综合平衡", "desc": "开采与生态保护协调的综合情景",
        "params": {
            "miningIntensity": 0.45, "restorationRate": 0.55, "policyConstraint": 0.60,
            "farmlandProtection": 0.60, "ecoRedline": 0.60, "waterProtection": 0.65,
            "dumpTreatment": 0.55, "urbanGrowth": 0.35, "forestExpansion": 0.45,
            "transportPull": 0.40, "neighborhoodWeight": 0.45, "suitabilityWeight": 0.50,
        },
    },
}

PARAM_LABELS = [
    ("miningIntensity", "采矿强度", "控制采矿用地扩张速率"),
    ("restorationRate", "生态修复强度", "采矿用地复垦为林地/耕地的速率"),
    ("policyConstraint", "政策约束", "限采政策对采矿与建设扩张的抑制"),
    ("farmlandProtection", "耕地保护", "基本农田保护强度"),
    ("ecoRedline", "生态红线", "高生态价值区域开发限制"),
    ("waterProtection", "水域保护", "水域及缓冲区保护强度"),
    ("dumpTreatment", "排土场治理", "未利用地复垦治理速率"),
    ("urbanGrowth", "建设用地扩张", "城镇与工业广场扩张速率"),
    ("forestExpansion", "林地扩散", "林地自然恢复与扩散速率"),
    ("transportPull", "交通牵引", "道路可达性对开发的吸引"),
    ("neighborhoodWeight", "邻域聚集权重", "CA 邻域密度在转换势中的权重"),
    ("suitabilityWeight", "适宜性权重", "CLUE-S 适宜性在转换势中的权重"),
]

IDX = {cid: i for i, cid in enumerate(geo.CLASS_IDS)}
I_FARM, I_FOREST, I_CONS, I_MINE, I_WATER, I_UNUSED = range(6)
HA_PER_PX = 0.09


def _resolve_params(scenario: str, override: dict | None) -> dict:
    params = dict(SCENARIOS[scenario]["params"])
    if override:
        params.update({k: float(v) for k, v in override.items() if k in params})
    return params


# ---------------------------------------------------------------- 转移矩阵
def transition_prob_matrix(a_year: int, b_year: int) -> np.ndarray:
    A, B = geo.load_landuse(a_year), geo.load_landuse(b_year)
    m = geo.transition_matrix(A, B).astype(np.float64)
    p = m / np.maximum(m.sum(axis=1, keepdims=True), 1)
    p = np.clip(p, 1e-4, None)
    return p / p.sum(axis=1, keepdims=True)


def matrix_at_years(P: np.ndarray, base_span: int, n_years: int) -> np.ndarray:
    """P 为 base_span 年跨度的转移矩阵 → 外推 n_years 年的等效矩阵"""
    alpha = n_years / float(base_span)
    if abs(alpha - 1.0) < 1e-9:
        return P
    Q = fractional_matrix_power(P, alpha).real
    Q = np.clip(Q, 0, None)
    return Q / Q.sum(axis=1, keepdims=True)


def adjust_matrix(P: np.ndarray, params: dict) -> np.ndarray:
    """情景参数 → 乘性因子修正转移矩阵（列向量因子 + 对角保护 + 行归一化）"""
    f = np.ones(6)
    f[I_MINE] += (params["miningIntensity"] - 0.5) * 1.4 - (params["policyConstraint"] - 0.4) * 1.2
    f[I_FOREST] += params["restorationRate"] * 1.6 + params["forestExpansion"] * 0.8
    f[I_CONS] += (params["urbanGrowth"] - 0.4) * 1.2 - params["policyConstraint"] * 0.5
    f[I_WATER] += params["waterProtection"] * 1.5
    f[I_FARM] += params["farmlandProtection"] * 1.2
    f[I_UNUSED] += params["dumpTreatment"] * 0.6
    f -= max(0.0, params["policyConstraint"] - 0.4) * 0.5
    f = np.clip(f, 0.05, None)

    Q = P * f[None, :]
    for idx, prot in ((I_FARM, params["farmlandProtection"]),
                      (I_WATER, params["waterProtection"]),
                      (I_FOREST, params["ecoRedline"] * 0.6),
                      (I_MINE, params["miningIntensity"] * 0.8)):
        Q[idx, idx] += prot * 1.5
    Q = np.clip(Q, 1e-5, None)
    return Q / Q.sum(axis=1, keepdims=True)


# ---------------------------------------------------------------- CLUE-S 适宜性
def calibrate_suitability(a_year: int, b_year: int):
    """以真实变化像元为样本，逐类拟合 Logistic 驱动因子回归"""
    A, B = geo.load_landuse(a_year), geo.load_landuse(b_year)
    dem = geo.load_driver("dem"); slope = geo.load_driver("slope")
    d_road = geo.load_driver("dist_road"); d_water = geo.load_driver("dist_water")
    d_mine = ndimage.distance_transform_edt(B != 4) * 30.0

    def norm(x):
        lo, hi = np.percentile(x, 1), np.percentile(x, 99)
        return np.clip((x - lo) / max(hi - lo, 1e-6), 0, 1)

    drivers = np.stack([
        norm(dem), norm(slope), norm(d_road), norm(d_water), norm(d_mine),
        np.ones_like(dem),
    ], axis=-1)

    changed = A != B
    rng = np.random.default_rng(1)
    stable_idx = np.flatnonzero(~changed.ravel())
    stable_idx = rng.choice(stable_idx, size=min(6000, stable_idx.size), replace=False)
    change_idx = np.flatnonzero(changed.ravel())
    sample_idx = np.concatenate([stable_idx, change_idx])
    rng.shuffle(sample_idx)

    X = drivers.reshape(-1, 6)[sample_idx]
    target_to = B.reshape(-1)[sample_idx]
    changed_mask = changed.reshape(-1)[sample_idx]

    models = {}
    for i, meta in enumerate(geo.CLASS_META):
        cid = meta["id"]
        y = ((changed_mask & (target_to == cid)) |
             (~changed_mask & (target_to == cid))).astype(int)
        n1, n0 = int(y.sum()), int((1 - y).sum())
        if n1 < 30 or n0 < 30:
            models[cid] = None
            continue
        lr = LogisticRegression(max_iter=300, C=1.0, class_weight="balanced")
        lr.fit(X, y)
        models[cid] = {
            "coef": [round(float(c), 4) for c in lr.coef_[0][:5]],
            "intercept": round(float(lr.intercept_[0]), 4),
            "n_pos": n1, "n_neg": n0,
            "driver_names": ["高程", "坡度", "距道路", "距水域", "距矿距离"],
        }
    return models, drivers


def suitability_maps(drivers: np.ndarray, models: dict) -> dict:
    """逐类适宜性概率面 (H,W) ∈ [0,1]，跨类 softmax 归一"""
    keys = []
    logits = []
    for meta in geo.CLASS_META:
        cid = meta["id"]
        m = models.get(cid)
        keys.append(cid)
        if m is None:
            logits.append(np.full(drivers.shape[:2], -1.0, dtype=np.float32))
        else:
            c = np.array(m["coef"] + [m["intercept"]], dtype=np.float32)
            logits.append(drivers @ c)
    L = np.stack(logits, axis=0)
    L -= L.max(axis=0, keepdims=True)
    E = np.exp(L)
    S = E / E.sum(axis=0, keepdims=True)
    return {k: S[i] for i, k in enumerate(keys)}


# ---------------------------------------------------------------- 约束层
def constraint_layers(params: dict) -> np.ndarray:
    """forbid[di, ci] = (H,W) bool：当前类 di 转为类 ci 的空间禁区"""
    dem = geo.load_driver("dem")
    slope = geo.load_driver("slope")
    last = geo.load_landuse(geo.years()[-1])
    water = last == 5
    wp, ep, fp = params["waterProtection"], params["ecoRedline"], params["farmlandProtection"]
    water_buf = ndimage.binary_dilation(water, iterations=int(2 + wp * 6))
    farm_flat = (last == 1) & (slope < 6) & (dem < np.percentile(dem, 40))
    redline = (slope > 18) & (dem > np.percentile(dem, 65))

    forbid = np.zeros((6, 6) + water.shape, dtype=bool)
    forbid[:, I_MINE] |= water_buf                                  # 采矿区避开水域缓冲
    if ep > 0.35:
        forbid[:, I_MINE] |= redline                                # 生态红线禁采
        if ep > 0.6:
            forbid[:, I_CONS] |= redline
    if fp > 0.35:
        forbid[:, I_MINE] |= farm_flat                              # 耕地保护
    if fp > 0.55:
        forbid[:, I_UNUSED] |= farm_flat
    if wp > 0.5:
        forbid[I_WATER, :] |= water                                 # 水域自身强保护
    return forbid


def road_pull(params: dict) -> np.ndarray:
    d = geo.load_driver("dist_road")
    d = np.clip(d / max(np.percentile(d, 95), 1e-6), 0, 1)
    return (1 - d) * params["transportPull"] * 0.5


# ---------------------------------------------------------------- 公共预测流程
def _demand_schedule(P, base_counts, base_span, b_year, target_year):
    """需求时间表：每年各类像元数（由基准年分布 × 矩阵分数幂外推）"""
    cur0 = base_counts.astype(np.float64)
    step = min(base_span, 5)
    schedule = []
    ys = list(range(b_year + step, target_year + 1, step))
    if not ys or ys[-1] != target_year:
        ys.append(target_year)
    for y in ys:
        Pt = matrix_at_years(P, base_span, y - b_year)
        nxt = cur0 @ Pt
        schedule.append((y, {geo.CLASS_META[i]["name"]: int(round(nxt[i])) for i in range(6)}))
    return schedule


def _predict_grid(a_year, b_year, target_year, params):
    """核心流程 → (预测栅格, 逐年面积表, 转移矩阵, 适宜性模型)"""
    P0 = transition_prob_matrix(a_year, b_year)
    P = adjust_matrix(P0, params)
    grid = geo.load_landuse(b_year).copy()
    counts0 = np.bincount(grid.reshape(-1), minlength=7)
    base_counts = np.array([counts0[geo.CLASS_IDS[i]] for i in range(6)], dtype=np.float64)

    models, drivers = calibrate_suitability(a_year, b_year)
    suit = suitability_maps(drivers, models)
    forbid = constraint_layers(params)

    wsum = params["neighborhoodWeight"] + params["suitabilityWeight"] + 0.5
    wN = params["neighborhoodWeight"] / wsum
    wS = params["suitabilityWeight"] / wsum
    wT = max(0.15, 1.0 - wN - wS)
    pull = road_pull(params)

    schedule = _demand_schedule(P, base_counts, b_year - a_year, b_year, target_year)
    history = []
    for y, demand in schedule:
        grid = _allocate(grid, demand, P, suit, forbid, wT, wN, wS, pull, iters=30)
        counts = np.bincount(grid.reshape(-1), minlength=7)
        history.append({
            "year": int(y),
            "areas": {geo.CLASS_META[i]["name"]: round(counts[geo.CLASS_IDS[i]] * HA_PER_PX, 1)
                      for i in range(6)},
        })
    return grid, history, P, models


def _allocate(grid, target, P, suit, forbid, wT, wN, wS, pull, iters=30):
    """CA 空间分配：按需求缺口迭代将盈余类像元转换为缺口类"""
    g = grid.copy()
    h, w = g.shape
    ids = np.array(geo.CLASS_IDS)
    tol = max(8.0, g.size * 0.0005)

    for _ in range(iters):
        counts = np.bincount(g.reshape(-1), minlength=7)
        cur = np.array([counts[geo.CLASS_IDS[i]] for i in range(6)], dtype=np.float64)
        tgt = np.array([target[geo.CLASS_META[i]["name"]] for i in range(6)], dtype=np.float64)
        diff = tgt - cur
        if np.abs(diff).sum() < tol:
            break
        donors = np.where(diff < -1)[0]
        if donors.size == 0:
            break
        donors = donors[np.argsort(diff[donors])]      # 优先消耗盈余最大的类
        donor_pool = np.isin(g, ids[donors])

        for ci in np.where(diff > 1)[0]:
            need = int(diff[ci])
            if need <= 0 or not donor_pool.any():
                continue
            pot = np.full((h, w), -1.0, dtype=np.float32)
            for di in donors:
                m = (g == ids[di]) & (~forbid[di, ci])
                if not m.any():
                    continue
                nb = ndimage.uniform_filter((g == ids[ci]).astype(np.float32), 5)
                pot[m] = wT * P[di, ci] + wN * nb[m] + wS * suit[ids[ci]][m] + pull[m]
            cand = pot > -0.5
            n_cand = int(cand.sum())
            if n_cand == 0:
                continue
            take = min(need, n_cand)
            flat = pot[cand]
            if take < n_cand:
                th = np.partition(flat, -take)[-take]
                sel = cand & (pot >= th) & (pot > -0.5)
                over = int(sel.sum()) - take
                if over > 0:
                    ys, xs = np.where(sel)
                    drop = np.random.rand(ys.size) < over / ys.size
                    sel[ys[drop], xs[drop]] = False
            else:
                sel = cand
            g[sel] = ids[ci]
            donor_pool &= ~_taken_mask(g, ids[ci], sel)
    return g


def _taken_mask(g, cid, sel):
    return sel & (g == cid)


# ---------------------------------------------------------------- 对外接口
def run_ca_markov(a_year, b_year, target_year, scenario="natural", params_override=None):
    params = _resolve_params(scenario, params_override)
    grid, history, P, models = _predict_grid(a_year, b_year, target_year, params)

    shade = geo.hillshade(geo.load_driver("dem"))
    base = geo.load_landuse(b_year)
    images = {}
    if history:
        images[str(history[-1]["year"])] = geo.render_landuse_png(
            grid, shade, legend=True,
            title=f"{geo.short_name()} {history[-1]['year']} 年土地利用预测（{SCENARIOS[scenario]['name']}情景）")
    images["change"] = geo.render_change_png(base, grid, shade)

    return {
        "model": "ca-markov",
        "scenario": scenario,
        "scenario_name": SCENARIOS[scenario]["name"],
        "params": params,
        "base": {"a": a_year, "b": b_year, "span": b_year - a_year},
        "transition_matrix": np.round(P, 4).tolist(),
        "area_history": history,
        "final_year": int(target_year),
        "suitability_models": {geo.name_of_class(k): v for k, v in models.items() if v},
        "images": images,
    }


def run_clues(a_year, b_year, target_year, scenario="natural", params_override=None):
    params = _resolve_params(scenario, params_override)
    models, drivers = calibrate_suitability(a_year, b_year)
    suit = suitability_maps(drivers, models)
    forbid = constraint_layers(params)

    grid = geo.load_landuse(b_year).copy()
    ids = np.array(geo.CLASS_IDS)

    # 需求模块：历史面积线性趋势外推 × 情景系数
    hist = np.vstack([
        (lambda c: [c[geo.CLASS_IDS[i]] for i in range(6)])(np.bincount(geo.load_landuse(y).reshape(-1), minlength=7))
        for y in geo.years()
    ]).astype(np.float64)
    ys = np.array(geo.years(), dtype=np.float64)
    trend = np.linalg.lstsq(np.vstack([ys, np.ones_like(ys)]).T, hist, rcond=None)[0]
    demand_px = trend[0] * float(target_year) + trend[1]
    demand_px = np.maximum(demand_px, 0)
    # 情景系数（半强度阻尼，避免线性外推过冲）
    damp = lambda m: 1 + (m - 1) * 0.45
    demand_px[I_MINE] *= damp(1 + (params["miningIntensity"] - 0.5) * 0.9 - (params["policyConstraint"] - 0.4) * 0.8)
    demand_px[I_FOREST] *= damp(1 + params["restorationRate"] * 0.6 + params["forestExpansion"] * 0.3)
    demand_px[I_UNUSED] *= damp(1 - params["dumpTreatment"] * 0.45)
    demand_px[I_CONS] *= damp(1 + (params["urbanGrowth"] - 0.4) * 0.8)
    demand_px = np.maximum(np.round(demand_px), 0).astype(int)
    s = demand_px.sum()
    if s > grid.size:
        demand_px = (demand_px / s * grid.size).astype(int)

    # 空间分配：适宜性排序 + 转换弹性（无 CA 邻域项）
    g = grid.copy()
    P0 = transition_prob_matrix(a_year, b_year)
    elasticity = 0.4 + params["neighborhoodWeight"] * 0.5
    for _ in range(200):
        counts = np.bincount(g.reshape(-1), minlength=7)
        cur = np.array([counts[geo.CLASS_IDS[i]] for i in range(6)])
        diff = demand_px - cur
        if np.abs(diff).sum() <= max(8, g.size * 0.0005):
            break
        ci = int(np.argmax(diff))
        if diff[ci] <= 1:
            break
        need = int(diff[ci])
        pot = np.full(g.shape, -1.0, dtype=np.float32)
        for di in range(6):
            if di == ci or P0[di, ci] < 0.01:
                continue
            m = (g == ids[di]) & (~forbid[di, ci])
            if m.any():
                pot[m] = suit[ids[ci]][m] + P0[di, ci] * elasticity
        cand = pot > -0.5
        n_cand = int(cand.sum())
        if n_cand == 0:
            break
        take = min(need, n_cand)
        flat = pot[cand]
        if take < n_cand:
            th = np.partition(flat, -take)[-take]
            sel = cand & (pot >= th) & (pot > -0.5)
            over = int(sel.sum()) - take
            if over > 0:
                yy, xx = np.where(sel)
                drop = np.random.rand(yy.size) < over / yy.size
                sel[yy[drop], xx[drop]] = False
        else:
            sel = cand
        g[sel] = ids[ci]

    shade = geo.hillshade(geo.load_driver("dem"))
    counts = np.bincount(g.reshape(-1), minlength=7)
    images = {str(target_year): geo.render_landuse_png(
        g, shade, legend=True,
        title=f"{geo.short_name()} {target_year} 年预测（CLUE-S·{SCENARIOS[scenario]['name']}）")}

    return {
        "model": "clues",
        "scenario": scenario,
        "scenario_name": SCENARIOS[scenario]["name"],
        "params": params,
        "base": {"a": a_year, "b": b_year},
        "demand_pixels": {geo.CLASS_META[i]["name"]: int(demand_px[i]) for i in range(6)},
        "area_history": [{
            "year": int(target_year),
            "areas": {geo.CLASS_META[i]["name"]: round(counts[geo.CLASS_IDS[i]] * HA_PER_PX, 1)
                      for i in range(6)},
        }],
        "final_year": int(target_year),
        "suitability_models": {geo.name_of_class(k): v for k, v in models.items() if v},
        "images": images,
    }


def compare_scenarios(a_year, b_year, target_year,
                      scenarios=("natural", "intensive", "ecological", "balanced")):
    results = []
    for sc in scenarios:
        r = run_ca_markov(a_year, b_year, target_year, sc)
        results.append({
            "scenario": sc,
            "scenario_name": SCENARIOS[sc]["name"],
            "desc": SCENARIOS[sc]["desc"],
            "final_areas": r["area_history"][-1]["areas"],
            "area_history": r["area_history"],
            "image": r["images"].get(str(target_year)),
        })
    return results


# ---------------------------------------------------------------- 精度验证
def validate(train_pair: tuple, target_year: int, scenario: str = "natural",
             truth=None, truth_title: str = ""):
    """精度验证：可用数据库该年实测地类，也可用用户导入的实测地类图作真值

    truth 非空时按导入图作真值（须已对齐到数据库网格、像元值为地类编号）。
    """
    a, b = train_pair
    params = _resolve_params(scenario, None)
    pred, history, P, models = _predict_grid(a, b, target_year, params)
    if truth is None:
        truth = geo.load_landuse(target_year)
    else:
        truth = np.asarray(truth)
        if truth.shape != pred.shape:
            raise ValueError(f"导入真值与数据库网格不一致：{truth.shape} vs {pred.shape}")
    truth_label = truth_title or (f"{target_year} 年实际土地利用" if truth_title == "" else truth_title)

    cm = geo.transition_matrix(pred, truth).astype(np.float64)
    oa = float(np.trace(cm) / cm.sum())
    pe = float((cm.sum(axis=0) * cm.sum(axis=1)).sum() / (cm.sum() ** 2))
    kappa = (oa - pe) / max(1 - pe, 1e-9)

    per_class = []
    for i, meta in enumerate(geo.CLASS_META):
        pa = cm[i, i] / max(cm[:, i].sum(), 1)
        ua = cm[i, i] / max(cm[i, :].sum(), 1)
        per_class.append({**meta, "producer_acc": round(pa * 100, 1), "user_acc": round(ua * 100, 1)})

    counts_t = np.bincount(truth.reshape(-1), minlength=7)
    counts_p = np.bincount(pred.reshape(-1), minlength=7)
    area_error = []
    for i, meta in enumerate(geo.CLASS_META):
        t, p = counts_t[geo.CLASS_IDS[i]], counts_p[geo.CLASS_IDS[i]]
        area_error.append({
            "name": meta["name"],
            "true_ha": round(t * HA_PER_PX, 1), "pred_ha": round(p * HA_PER_PX, 1),
            "err_pct": round((p - t) / max(t, 1) * 100, 2),
        })

    shade = geo.hillshade(geo.load_driver("dem"))
    images = {
        "predicted": geo.render_landuse_png(pred, shade, legend=True,
                                            title=f"{target_year} 年预测结果（训练期 {a}-{b}）"),
        "truth": geo.render_landuse_png(truth, shade, legend=True,
                                        title=truth_label),
    }
    return {
        "truth_title": truth_label,
        "train": {"a": a, "b": b}, "target_year": target_year,
        "scenario": scenario, "scenario_name": SCENARIOS[scenario]["name"],
        "overall_accuracy": round(oa * 100, 2),
        "kappa": round(float(kappa), 4),
        "confusion_matrix": cm.astype(int).tolist(),
        "per_class": per_class,
        "area_error": area_error,
        "images": images,
    }
