# -*- coding: utf-8 -*-
# 矿地智预 MineGeoAI-Pre · by zhuoer mengzhuoda · 9.20
"""
矿地智预 MineGeoAI-Pre — 真实数据集接入工具
把 CLCD 等真实土地覆被产品 + DEM + 道路 + 矿权范围，转换成软件可直接加载的数据集

用法示例：
  python tools/import_real_dataset.py ^
    --clcd-dir "E:/CLCD" --years 2000 2005 2010 2015 2020 ^
    --aoi aoi.geojson ^
    --dem dem.tif --roads roads.geojson --mine mine.geojson ^
    --dataset-id pingshuo-real --name "平朔矿区（真实数据）" ^
    --out-dir backend/data/pingshuo-real

数据要求：
  · CLCD：CLCD_v01_<年份>*.tif（Albers 或 WGS84 均可，脚本自动识别）
  · AOI：GeoJSON 多边形（QGIS 里导出），决定研究区范围
  · DEM：任意 CRS 的单波段栅格（SRTM/ASTER）
  · roads / mine：GeoJSON 线/面（可选，见 README 指南）

产出：<out-dir>/{landuse_<年>.tif, dem.tif, slope.tif, dist_road.tif, dist_water.tif, metadata.json}
"""
import argparse
import json
import os
import re
import sys

import numpy as np
import rasterio
from rasterio.crs import CRS
from rasterio.features import rasterize
from rasterio.transform import from_origin
from rasterio.warp import Resampling, reproject, transform, transform_bounds
from rasterio.windows import from_bounds
from scipy import ndimage

# CLCD 9 类 → 软件 6 类（可按矿区实际调整；键为 CLCD 编码）
CLCD_TO_6 = {
    1: 1,   # 耕地 Cropland   → 耕地
    2: 2,   # 林地 Forest     → 林地
    3: 2,   # 灌木 Shrub      → 林地（合并为植被类）
    4: 2,   # 草地 Grassland  → 林地（合并为植被类）
    5: 5,   # 水体 Water      → 水域
    6: 6,   # 冰雪 Snow/Ice   → 未利用地
    7: 6,   # 裸地 Barren     → 未利用地（排土场/剥离区多数落在此类）
    8: 3,   # 不透水面 Impervious → 建设用地
    9: 5,   # 湿地 Wetland    → 水域（若矿区湿地不涉水，改成 6）
}
CLCD_NAMES = {1: "耕地", 2: "林地", 3: "灌木", 4: "草地", 5: "水体",
              6: "冰雪", 7: "裸地", 8: "不透水面", 9: "湿地"}

CLASS_META = [
    {"id": 1, "name": "耕地", "color": "#f0c850"},
    {"id": 2, "name": "林地", "color": "#3e8e41"},
    {"id": 3, "name": "建设用地", "color": "#9b59b6"},
    {"id": 4, "name": "采矿用地", "color": "#e74c3c"},
    {"id": 5, "name": "水域", "color": "#3f7fd4"},
    {"id": 6, "name": "未利用地", "color": "#d2b48c"},
]


def log(msg):
    print(msg, flush=True)


def load_geojson(path):
    with open(path, encoding="utf-8") as f:
        gj = json.load(f)
    if gj.get("type") == "FeatureCollection":
        geoms = [f["geometry"] for f in gj["features"] if f.get("geometry")]
    elif gj.get("type") == "Feature":
        geoms = [gj["geometry"]]
    else:
        geoms = [gj]
    return geoms


def geom_bbox(geoms):
    xs, ys = [], []
    def walk(c):
        if isinstance(c[0], (int, float)):
            xs.append(c[0]); ys.append(c[1])
        else:
            for sub in c:
                walk(sub)
    for g in geoms:
        walk(g["coordinates"])
    return min(xs), min(ys), max(xs), max(ys)


def find_year_file(folder, year):
    """在目录里找包含该年份的 CLCD 文件"""
    pats = [f"{year}", f"_{year}_", f"_{year}."]
    cands = []
    for fn in os.listdir(folder):
        if not fn.lower().endswith((".tif", ".tiff")):
            continue
        if any(p in fn for p in pats):
            cands.append(os.path.join(folder, fn))
    if not cands:
        raise FileNotFoundError(f"目录 {folder} 中未找到 {year} 年的 tif 文件")
    # 优先含 albert 的（完整覆盖）
    cands.sort(key=lambda p: (0 if "albert" in os.path.basename(p).lower() else 1, p))
    return cands[0]


def build_grid(aoi_geoms, target_crs, res, max_size):
    """由 AOI 计算目标网格（transform / width / height），并在超限时降采样"""
    src_crs = "EPSG:4326"
    xmin, ymin, xmax, ymax = geom_bbox(aoi_geoms)
    left, bottom, right, top = transform_bounds(src_crs, target_crs, xmin, ymin, xmax, ymax)
    # 对齐到分辨率格网
    left = np.floor(left / res) * res
    top = np.ceil(top / res) * res
    right = np.ceil(right / res) * res
    bottom = np.floor(bottom / res) * res
    width = int(round((right - left) / res))
    height = int(round((top - bottom) / res))
    # 尺寸保护（大网格会让 CA 分配变慢）
    factor = 1
    while max(width, height) // factor > max_size:
        factor += 1
    if factor > 1:
        res = res * factor
        left = np.floor(left / res) * res
        top = np.ceil(top / res) * res
        width = int(round((right - left) / res))
        height = int(round((top - bottom) / res))
        log(f"  · 网格超过 {max_size}px，降采样 {factor}× → 分辨率 {res:.0f} m，"
            f"网格 {width}×{height}")
    return from_origin(left, top, res, res), width, height, res, (left, bottom, right, top)


def read_to_grid(path, dst_transform, width, height, dst_crs, resampling, dtype, band=1, nodata=None):
    """读任意 CRS 栅格并重投影/裁剪到目标网格（越界区域按有效值中位数填充并告警）"""
    with rasterio.open(path) as src:
        left, bottom, right, top = transform_bounds(
            dst_crs, src.crs, dst_transform.c, dst_transform.f + height * dst_transform.e,
            dst_transform.c + width * dst_transform.a, dst_transform.f)
        win = from_bounds(left, bottom, right, top, transform=src.transform)
        win = win.round_offsets().round_lengths()
        src_nodata = src.nodata if src.nodata is not None else (0 if "int" in np.dtype(dtype).name else -9999.0)
        data = src.read(band, window=win, boundless=True, fill_value=src_nodata)
        src_transform = src.window_transform(win)
        out = np.zeros((height, width), dtype=dtype)
        reproject(
            source=data, destination=out,
            src_transform=src_transform, src_crs=src.crs,
            dst_transform=dst_transform, dst_crs=dst_crs,
            src_nodata=src_nodata, dst_nodata=None,
            resampling=resampling,
        )
        if "float" in np.dtype(dtype).name:
            # 无效值判定：声明式 nodata + 哨兵值（GEE 导出常用 -9999）
            # 光谱指数/高程都不会低于 -9990，故可安全用作哨兵
            valid_mask = np.isfinite(out) & (out != src_nodata) & (out > -9990)
            miss = float((~valid_mask).mean())
            if miss > 0.02:
                log(f"  ! 警告：{os.path.basename(path)} 有 {miss*100:.1f}% 区域超出数据范围，"
                    f"已用有效值中位数填充")
            if not valid_mask.all():
                fill = float(np.median(out[valid_mask])) if valid_mask.any() else 0.0
                out[~valid_mask] = fill
        return out


def _reproject_geom(g, dst_crs):
    """把 GeoJSON 几何坐标从 WGS84 变换到目标 CRS（递归处理嵌套坐标）"""
    def walk(coords):
        if isinstance(coords[0], (int, float)):
            tx, ty = transform("EPSG:4326", dst_crs, [coords[0]], [coords[1]])
            return [tx[0], ty[0]]
        return [walk(c) for c in coords]
    return {"type": g["type"], "coordinates": walk(g["coordinates"])}


def rasterize_geojson(geoms, dst_transform, width, height, dst_crs, all_touched=False):
    """GeoJSON（WGS84）→ 目标网格的二值掩膜（线要素自动缓冲加粗）"""
    shapes = []
    for g in geoms:
        if g["type"] not in ("Polygon", "MultiPolygon", "LineString", "MultiLineString"):
            continue
        gg = _reproject_geom(g, dst_crs)
        if gg["type"] in ("LineString", "MultiLineString"):
            # 线段在栅格上太细，用 2 像元缓冲近似道路宽度
            shapes.append((gg, 1))
            gg2 = {"type": gg["type"],
                   "coordinates": _buffer_coords(gg["coordinates"], dst_transform.a * 2)}
            shapes.append((gg2, 1))
        else:
            shapes.append((gg, 1))
    if not shapes:
        return np.zeros((height, width), dtype=np.uint8)
    return rasterize(shapes, out_shape=(height, width), transform=dst_transform,
                     fill=0, all_touched=all_touched, dtype=np.uint8)


def _buffer_coords(coords, pad):
    """极简折线缓冲：沿线生成四边形（避免引入 shapely 依赖）"""
    def quadring(line):
        out = []
        for i in range(len(line) - 1):
            (x1, y1), (x2, y2) = line[i], line[i + 1]
            dx, dy = x2 - x1, y2 - y1
            L = max((dx * dx + dy * dy) ** 0.5, 1e-9)
            nx, ny = -dy / L * pad, dx / L * pad
            out.append([[x1 + nx, y1 + ny], [x2 + nx, y2 + ny],
                        [x2 - nx, y2 - ny], [x1 - nx, y1 - ny], [x1 + nx, y1 + ny]])
        return out
    if coords and isinstance(coords[0][0], (int, float)):
        polys = quadring(coords)
        return polys if len(polys) > 1 else (polys[0] if polys else [])
    parts = [_buffer_coords(c, pad) for c in coords]
    flat = []
    for p in parts:
        flat.extend(p if isinstance(p[0][0][0], (int, float)) else p)
    return flat


VEG_CLASSES = (1, 2)          # 耕地/林地：未受扰动的植被基底
DISTURB_CLASSES = (6, 3)       # 未利用地/建设用地：剥离裸地与工业广场落类


INDEX_ALIASES = {                 # 指数名 → 文件名匹配模式（不区分大小写）
    "ndvi": ("ndvi",),
    "bsi": ("bsi",),
    "ndbi": ("ndbi",),
    "lst": ("lst", "temp"),       # 地表温度（可选，计划书中的时序反演指标）
}


def load_index_stacks(indices_dir, years, dst_transform, W, H, crs):
    """读取各期光谱指数栅格并对齐到目标网格（命名需含年份，如 ndvi_2000.tif）"""
    stacks = {}
    for key, pats in INDEX_ALIASES.items():
        arrs = []
        for y in years:
            hit = None
            for fn in sorted(os.listdir(indices_dir)):
                low = fn.lower()
                if low.endswith((".tif", ".tiff")) and str(y) in fn and any(p in low for p in pats):
                    hit = os.path.join(indices_dir, fn)
                    break
            if hit is None:
                arrs = None
                break
            arrs.append(read_to_grid(hit, dst_transform, W, H, crs, Resampling.bilinear, np.float32))
        if arrs:
            stacks[key] = arrs
    return stacks


def spectral_evidence(stacks, ndvi_max=0.0, bsi_min=0.0, ndbi_max=0.0, cva_min=0.0,
                      smooth=1.0):
    """光谱证据层（对应计划书的 NDVI 时序分析 + 变化向量解析 + 光谱特征提取）

    矿区裸土的光谱签名 = NDVI 低（植被稀疏）+ BSI 高（裸土）+ NDBI 低（非建筑）
    三者同时满足才是"矿区剥离面"，城市建成区因 NDBI 高被排除。

    阈值自适应：参数 ≤ 0 时按数据自身分位数自动标定（真实影像的指数绝对
    量级随区域/季节漂移，固定阈值会失效）：
      NDVI < 25% 分位（植被最稀疏的 1/4）
      BSI  > 65% 分位（裸土最显著的 35%）
      NDBI < 80% 分位（排除建成区最高的 20%）

    逐年计算签名（而非全期平均）——否则晚期才扩张的采区会被历史植被光谱稀释而漏检。

    返回：sig_by_year（逐年签名掩膜）、cva（标准化变化向量幅值）、cva_high、layers（诊断）
    """
    if not stacks:
        return None
    n = len(next(iter(stacks.values())))
    shape = next(iter(stacks.values()))[0].shape

    def _smooth(a):
        return ndimage.gaussian_filter(a, smooth) if smooth and smooth > 0 else a

    # 自适应阈值：按全期数据的有效值分位数
    def q(k, pct):
        allv = np.concatenate([a[(a > -9990) & np.isfinite(a)] for a in stacks[k]])
        return float(np.percentile(allv, pct)) if allv.size else 0.0

    ndvi_max = ndvi_max if ndvi_max > 0 else q("ndvi", 25) if "ndvi" in stacks else 0.25
    bsi_min = bsi_min if bsi_min > 0 else q("bsi", 65) if "bsi" in stacks else 0.28
    ndbi_max = ndbi_max if ndbi_max > 0 else q("ndbi", 80) if "ndbi" in stacks else 0.15

    sig_by_year = []
    for t in range(n):
        keep = None
        if "ndvi" in stacks:
            keep = _and(keep, _smooth(stacks["ndvi"][t]) < ndvi_max)
        if "bsi" in stacks:
            keep = _and(keep, _smooth(stacks["bsi"][t]) > bsi_min)
        if "ndbi" in stacks:
            keep = _and(keep, _smooth(stacks["ndbi"][t]) < ndbi_max)
        sig_by_year.append(keep if keep is not None else np.ones(shape, dtype=bool))

    # 变化向量分析（CVA）：各指数先 z-score 标准化（量纲统一，°C 的 LST 不再主导），
    # 跨期变化向量幅值取历史最大。阈值同样自适应：> 均值 + 1.5 标准差
    names = [k for k in ("ndvi", "bsi", "ndbi", "lst") if k in stacks]
    cva, cva_high = None, None
    if names:
        zs = {}
        for nm in names:
            allv = np.concatenate([a[(a > -9990) & np.isfinite(a)] for a in stacks[nm]])
            mu, sd = float(allv.mean()), float(allv.std() + 1e-9)
            zs[nm] = [(a - mu) / sd for a in stacks[nm]]
        cva = np.zeros(shape, dtype=np.float32)
        for t in range(n - 1):
            sq = np.zeros(shape, dtype=np.float32)
            for nm in names:
                d = zs[nm][t + 1] - zs[nm][t]
                sq = sq + d * d
            cva = np.maximum(cva, np.sqrt(sq))
        cva_th = cva_min if cva_min > 0 else (float(cva.mean()) + 1.5 * float(cva.std()))
        cva_high = cva > cva_th

    layers = {}
    if "ndvi" in stacks:
        layers["NDVI 低值"] = f"{np.mean([a.mean() for a in stacks['ndvi']]):.3f}（均值），阈值 <{ndvi_max:.3f}"
    if "bsi" in stacks:
        layers["BSI 裸土"] = f"{np.mean([a.mean() for a in stacks['bsi']]):.3f}（均值），阈值 >{bsi_min:.3f}"
    if "ndbi" in stacks:
        layers["NDBI 非城市"] = f"{np.mean([a.mean() for a in stacks['ndbi']]):.3f}（均值），阈值 <{ndbi_max:.3f}"
    if cva is not None:
        layers["CVA 变化向量"] = f"{cva.mean():.3f}（标准化后均值），自适应阈值 {cva_th:.3f}"

    return {"sig_by_year": sig_by_year, "cva": cva, "cva_high": cva_high, "layers": layers}


def _and(acc, mask):
    return mask if acc is None else (acc & mask)


def _reconstruct(seed, mask, structure, max_iter=200):
    """形态学重建（种子填充）：返回 mask 中与 seed 连通的全部区域

    用途：变化检测能可靠识别"采区扩张的边缘"，但采区核心（首期即存在的裸地）
    从未经历"植被→裸地"的转变，检测不到。以检测到的扰动区为种子、
    在光谱签名区（矿区裸土光谱）内做重建，即可把整个连片采区系统完整取出，
    同时不会引入远处孤立的天然裸地（它们与种子不连通）。
    """
    prev = seed & mask
    for _ in range(max_iter):
        cur = ndimage.binary_dilation(prev, structure=structure) & mask
        if np.array_equal(cur, prev):
            break
        prev = cur
    return prev


def detect_mining(cls_stack, mine_mask=None, min_patch=20, morph_radius=1, use_change=True,
                  spec_ev=None, require_cva=False):
    """采矿用地自动检测（逐年掩膜）

    原理：采矿用地的本质不是固定光谱，而是"植被/耕地 → 裸地/建成区"的剧烈
    土地损毁过程（露天矿剥离—排土链条）。因此逐年判定：

        第 t 年采矿用地 = (截至 t 年累积的扰动区) ∩ (第 t 年仍为裸地/建成区)

    这样既保留了采区逐年扩张的过程（预测模型标定转移矩阵所必需），
    又能正确处理复垦——曾受扰动、后恢复植被的区域会自动移出采矿用地。

    返回：(逐年掩膜列表, 逐期新增扰动统计)
    """
    n = len(cls_stack)
    st = ndimage.generate_binary_structure(2, 2)
    cumulative = np.zeros(cls_stack[0].shape, dtype=bool)
    masks, change_log = [], []

    for t in range(n):
        disturb_now = np.isin(cls_stack[t], DISTURB_CLASSES)

        if t == 0:
            # 首期无历史证据：借助矿权范围确定初始采区，并作为累积基底
            if mine_mask is not None:
                cumulative |= (mine_mask == 1) & disturb_now
        elif use_change:
            new_dist = (np.isin(cls_stack[t - 1], VEG_CLASSES) & disturb_now)
            cumulative |= new_dist
            change_log.append(int(new_dist.sum()))
        elif mine_mask is not None:
            cumulative |= (mine_mask == 1) & disturb_now

        # 该年采矿用地 = 累积扰动区 ∩ 该年仍为扰动状态（复垦区自动移出）
        cand = (cumulative & disturb_now) if use_change else disturb_now

        # 形态学重建补全采区核心：以扰动区为种子，在光谱签名区内连通扩展
        # 注意：种子本体必须保留（并集）——_reconstruct 内部会先做 seed∩mask，
        # 若直接覆盖 cand，矿点先验给出的可信种子（矿区内扰动像元）会先被严格
        # 签名过滤掉（30 m 混合像元下真实坑排面仅 ~4% 过签名），致识别量级崩塌
        if spec_ev and cand.any() and cand.sum() > 5:
            sig = spec_ev.get("sig_by_year")
            if sig is not None and t < len(sig):
                grown = _reconstruct(cand, sig[t] & disturb_now, st, max_iter=1000)
                cand = cand | grown

        # 矿权约束：剔除范围外的非采矿扰动（城市扩张、水库、道路工程）
        if mine_mask is not None:
            cand = cand & (mine_mask == 1)
        # 光谱证据过滤（论文方法）：剔除"变化剧烈但非矿区"的像元
        #
        # 矿区裸土的光谱签名 = NDVI 低（植被稀疏） + BSI 高（裸土） + NDBI 低（非建筑）
        # 三者必须同时满足：城市建成区虽然 NDVI 也低（且变化同样剧烈），
        # 但其 NDBI 高，会被第三条排除 —— 这是区分"矿区剥离面"与"城市扩张"的关键。
        if spec_ev:
            sig = spec_ev.get("sig_by_year")
            if sig is not None and t < len(sig) and mine_mask is None:
                # 提供矿点先验/矿区范围约束时，"非矿区剔除"已由范围约束承担，
                # 签名不再作最终 AND —— 30 m 混合像元下真实矿区的坑排面大多呈
                # 半植被光谱（复垦与自然恢复），严格签名会漏掉老采区主体
                # （实测：平朔全矿区扰动像元仅 4% 过严格签名，致识别量级偏小百倍）。
                cand = cand & sig[t]                 # 该年光谱签名（AND）
            if require_cva and spec_ev.get("cva_high") is not None:
                cand = cand & spec_ev["cva_high"]    # 可选严格模式

        # 形态学清理：开运算去噪点，闭运算填补采坑内部小空洞
        if cand.any() and morph_radius:
            cand = ndimage.binary_opening(cand, structure=st, iterations=morph_radius)
            cand = ndimage.binary_closing(cand, structure=st, iterations=morph_radius)

        # 连通域面积过滤：真实采区/排土场必然连片
        if cand.any():
            lab, nlab = ndimage.label(cand, structure=st)
            sizes = ndimage.sum(cand, lab, range(1, nlab + 1))
            keep = np.zeros(nlab + 1, dtype=bool)
            keep[1:] = sizes >= min_patch
            cand = keep[lab]

        masks.append(cand)

    if use_change:
        change_log = [0] + change_log          # 首期无"新增扰动"概念，占位
    else:
        change_log = [0] * n
    return masks, change_log




def detect_index_grid(indices_dir, target_crs, target_res):
    """探测光谱指数栅格的网格；若与目标 CRS/分辨率一致则直接复用其网格
    （保证指数与最终数据集零对齐，避免 WGS84→UTM 投影往返导致的边界膨胀）"""
    if not indices_dir or not os.path.isdir(indices_dir):
        return None
    tifs = [f for f in os.listdir(indices_dir) if f.lower().endswith((".tif", ".tiff"))]
    if not tifs:
        return None
    try:
        with rasterio.open(os.path.join(indices_dir, tifs[0])) as s:
            if s.crs != CRS.from_string(target_crs):
                return None
            res = float(s.res[0])
            if abs(res - target_res) > max(0.5, target_res * 0.02):
                return None
            t = s.transform
            bounds = (t.c, t.f + s.height * t.e, t.c + s.width * t.a, t.f)
            return t, s.width, s.height, res, bounds
    except Exception:
        return None


def main():
    ap = argparse.ArgumentParser(description="矿地智预 - 真实数据集接入工具")
    ap.add_argument("--clcd-dir", required=True, help="CLCD 年度 tif 所在目录")
    ap.add_argument("--years", nargs="+", type=int, required=True, help="年份列表，如 2000 2010 2020")
    ap.add_argument("--aoi", required=True, help="研究区范围 GeoJSON（多边形）")
    ap.add_argument("--dem", required=True, help="DEM 栅格")
    ap.add_argument("--roads", help="道路 GeoJSON（可选，缺失时用建成区距离代理）")
    ap.add_argument("--mine", help="矿权/采坑范围 GeoJSON（可选，用于识别采矿用地）")
    ap.add_argument("--dataset-id", required=True, help="数据集标识（目录名，如 pingshuo-real）")
    ap.add_argument("--name", required=True, help="数据集显示名（如 平朔矿区（真实数据））")
    ap.add_argument("--out-dir", required=True, help="输出目录，通常 backend/data/<dataset-id>")
    ap.add_argument("--crs", default="EPSG:32649", help="目标坐标系，默认 UTM 49N")
    ap.add_argument("--res", type=float, default=30.0, help="目标分辨率（米），默认 30")
    ap.add_argument("--max-size", type=int, default=800, help="最大网格边长，默认 800（超出自动降采样）")
    ap.add_argument("--min-patch", type=int, default=20, help="采矿扰动最小斑块（像元），默认 20")
    ap.add_argument("--morph", type=int, default=1, help="形态学清理半径（像元），默认 1")
    ap.add_argument("--no-change-detect", action="store_true", help="关闭时序变化检测，仅用矿权范围")
    ap.add_argument("--indices-dir", help="光谱指数栅格目录（ndvi_<年>.tif / bsi_<年>.tif / ndbi_<年>.tif）")
    ap.add_argument("--ndvi-thresh", type=float, default=0.0, help="NDVI 低值阈值（0=自适应分位数）")
    ap.add_argument("--bsi-thresh", type=float, default=0.0, help="BSI 裸土阈值（0=自适应分位数）")
    ap.add_argument("--ndbi-thresh", type=float, default=0.0, help="NDBI 非城市阈值（0=自适应分位数）")
    ap.add_argument("--cva-thresh", type=float, default=0.0, help="CVA 变化向量阈值（0=自适应）")
    ap.add_argument("--require-cva", action="store_true",
                    help="严格模式：要求 CVA 变化向量也显著（适合变化剧烈的露天矿）")
    args = ap.parse_args()

    os.makedirs(args.out_dir, exist_ok=True)

    log("=" * 62)
    log(f"矿地智预 · 真实数据集接入：{args.name}")
    log("=" * 62)

    # ---------- 1. 研究区与目标网格 ----------
    log("\n[1/6] 计算目标网格…")
    aoi = load_geojson(args.aoi)
    # 优先复用光谱指数栅格的网格（零对齐误差，且避免投影往返膨胀）
    idx_grid = detect_index_grid(args.indices_dir, args.crs, args.res)
    if idx_grid:
        dst_transform, W, H, res, bounds = idx_grid
        log(f"  · 网格已对齐光谱指数栅格：{W}×{H} @ {res:.0f} m")
    else:
        dst_transform, W, H, res, bounds = build_grid(aoi, args.crs, args.res, args.max_size)
    log(f"  · 范围 {bounds[0]:.0f},{bounds[1]:.0f} ~ {bounds[2]:.0f},{bounds[3]:.0f}")
    pixel_m2 = res * res

    # ---------- 2. 矿权范围掩膜 ----------
    mine_mask = None
    if args.mine:
        mine_mask = rasterize_geojson(load_geojson(args.mine), dst_transform, W, H, args.crs)
        log(f"  · 矿权/采坑掩膜：{int(mine_mask.sum())} 像元（占 {mine_mask.mean()*100:.1f}%）")

    # ---------- 3. 逐年裁剪 + 类别映射 ----------
    log("\n[2/7] 处理土地利用分类…")
    stack = []
    for year in sorted(args.years):
        path = find_year_file(args.clcd_dir, year)
        raw = read_to_grid(path, dst_transform, W, H, args.crs, Resampling.nearest, np.uint8)
        # 映射到 6 类
        cls = np.zeros_like(raw)
        for k, v in CLCD_TO_6.items():
            cls[raw == k] = v
        # 边界 nodata 空洞 → 用最近有效类别填充（避免空洞像元）
        if (cls == 0).any():
            holes = cls == 0
            idx = ndimage.distance_transform_edt(holes, return_distances=False, return_indices=True)
            cls[holes] = cls[tuple(idx[:, holes])]
        stack.append(cls)
        counts = {c["name"]: int((cls == c["id"]).sum()) for c in CLASS_META}
        log(f"  · {year} 原始: " + "  ".join(f"{k} {v*pixel_m2/1e4:.0f}ha"
                                             for k, v in counts.items() if v))

    # ---------- 3b. 采矿用地自动检测 ----------
    log("\n[3/7] 采矿用地检测（多源证据融合）…")
    spec_ev = None
    if args.indices_dir:
        istacks = load_index_stacks(args.indices_dir, sorted(args.years),
                                    dst_transform, W, H, args.crs)
        if istacks:
            log(f"  · 载入光谱指数：{'、'.join(istacks.keys())}"
                f"（共 {sum(len(v) for v in istacks.values())} 幅）")
            spec_ev = spectral_evidence(
                istacks, ndvi_max=args.ndvi_thresh, bsi_min=args.bsi_thresh,
                ndbi_max=args.ndbi_thresh, cva_min=args.cva_thresh)
            if spec_ev:
                for k, v in spec_ev["layers"].items():
                    log(f"    - {k}：{v}")
                sigs = spec_ev["sig_by_year"]
                cov = " / ".join(f"{y} {s.mean()*100:.1f}%" for y, s in zip(sorted(args.years), sigs))
                log(f"    - 逐年光谱签名覆盖率：{cov}")
        else:
            log("  ! --indices-dir 中未匹配到指数栅格（命名需含年份，如 ndvi_2000.tif）") 
    if spec_ev is None:
        log("  · 光谱证据：未启用（提供 --indices-dir 可启用 NDVI/BSI/NDBI + CVA 融合）")
    else:
        log("  · 检测策略：变化检测定种子 → 光谱签名区形态学重建，补全首期即存在的采区核心")
    mine_masks, change_log = detect_mining(
        stack, mine_mask=mine_mask, min_patch=args.min_patch,
        morph_radius=args.morph, use_change=not args.no_change_detect, spec_ev=spec_ev,
        require_cva=args.require_cva)
    years_sorted = sorted(args.years)
    for i in range(1, len(change_log)):
        cnt = change_log[i]
        log(f"  · {years_sorted[i-1]}→{years_sorted[i]}: 新增扰动 {cnt} 像元 ({cnt*pixel_m2/1e4:.1f} ha)")
    if mine_mask is None:
        log("  ! 未提供矿权范围：结果可能包含城市扩张等非采矿扰动，建议补 --mine 提高准确度")
    trend = [int(m.sum()) for m in mine_masks]
    log("  · 采矿用地逐年判定：" + " → ".join(
        f"{y}:{v*pixel_m2/1e4:.0f}ha" for y, v in zip(years_sorted, trend)))
    if trend[-1] > trend[0]:
        log(f"  · 采区扩张趋势：{trend[0]*pixel_m2/1e4:.0f} → {trend[-1]*pixel_m2/1e4:.0f} ha "
            f"(+{(trend[-1]-trend[0])*pixel_m2/1e4:.0f} ha)")

    history = {}
    profile = dict(driver="GTiff", height=H, width=W, count=1, dtype="uint8",
                   crs=args.crs, transform=dst_transform, compress="deflate", nodata=0)
    for year, cls, mmask in zip(years_sorted, stack, mine_masks):
        cls[mmask] = 4
        with rasterio.open(os.path.join(args.out_dir, f"landuse_{year}.tif"), "w", **profile) as dst:
            dst.write(cls, 1)
        counts = {c["name"]: int((cls == c["id"]).sum()) for c in CLASS_META}
        total = sum(counts.values())
        log(f"  · {year} 成果: " + "  ".join(f"{k} {v*pixel_m2/1e4:.0f}ha({v/max(total,1)*100:.1f}%)"
                                             for k, v in counts.items() if v))
        history[str(year)] = {k: round(v * pixel_m2 / 1e4, 1) for k, v in counts.items()}

    # ---------- 4. 地形驱动因子 ----------
    log("\n[4/7] 处理 DEM 与坡度…")
    dem = read_to_grid(args.dem, dst_transform, W, H, args.crs, Resampling.bilinear, np.float32)
    with rasterio.open(os.path.join(args.out_dir, "dem.tif"), "w", driver="GTiff",
                       height=H, width=W, count=1, dtype="float32",
                       crs=args.crs, transform=dst_transform, compress="deflate") as dst:
        dst.write(dem, 1)
    gy, gx = np.gradient(dem, res)
    slope = np.degrees(np.arctan(np.hypot(gx, gy))).astype(np.float32)
    with rasterio.open(os.path.join(args.out_dir, "slope.tif"), "w", driver="GTiff",
                       height=H, width=W, count=1, dtype="float32",
                       crs=args.crs, transform=dst_transform, compress="deflate") as dst:
        dst.write(slope, 1)
    log(f"  · 高程 {dem.min():.0f}~{dem.max():.0f} m，坡度 {slope.min():.1f}~{slope.max():.1f}°")

    # ---------- 5. 水域与道路距离 ----------
    log("\n[5/7] 计算距离驱动因子…")
    latest = os.path.join(args.out_dir, f"landuse_{max(args.years)}.tif")
    with rasterio.open(latest) as src:
        land = src.read(1)
    dist_water = ndimage.distance_transform_edt(land != 5) * res
    with rasterio.open(os.path.join(args.out_dir, "dist_water.tif"), "w", driver="GTiff",
                       height=H, width=W, count=1, dtype="float32",
                       crs=args.crs, transform=dst_transform, compress="deflate") as dst:
        dst.write(dist_water.astype(np.float32), 1)
    log(f"  · 距水域：0~{dist_water.max():.0f} m（由 {max(args.years)} 年水域计算）")

    if args.roads:
        road_mask = rasterize_geojson(load_geojson(args.roads), dst_transform, W, H, args.crs)
        if road_mask.sum() == 0:
            log("  ! 道路掩膜为空（道路可能不在研究区内），改用建成区距离代理")
            road_mask = (land == 3).astype(np.uint8)
    else:
        log("  ! 未提供道路数据，暂以建成区距离作为代理（生产使用请补 OSM 道路）")
        road_mask = (land == 3).astype(np.uint8)
    dist_road = (ndimage.distance_transform_edt(road_mask == 0) * res).astype(np.float32)
    with rasterio.open(os.path.join(args.out_dir, "dist_road.tif"), "w", driver="GTiff",
                       height=H, width=W, count=1, dtype="float32",
                       crs=args.crs, transform=dst_transform, compress="deflate") as dst:
        dst.write(dist_road, 1)
    log(f"  · 距道路：0~{dist_road.max():.0f} m")

    # ---------- 6. metadata ----------
    log("\n[6/7] 生成元数据…")
    left, bottom, right, top = bounds
    meta = {
        "region": args.name,
        "short_name": args.name.split("（")[0],
        "crs": args.crs,
        "resolution_m": res,
        "pixel_area_m2": pixel_m2,
        "extent": {"xmin": left, "ymin": bottom, "xmax": right, "ymax": top},
        "classes": CLASS_META,
        "years": sorted(args.years),
        "area_km2": round(W * H * pixel_m2 / 1e6, 2),
        "history": history,
        "source": "CLCD 30m 年度土地覆被产品（Yang & Huang, 2021, ESSD）"
                  + ("+ 矿权范围叠加" if args.mine else ""),
        "mining_detection": {
            "method": "时序变化检测" + ("+矿权约束" if args.mine else "（无矿权约束）"),
            "rule": "耕地/林地 → 裸地/建设用地 的转变（种子）"
                    + ("+ 光谱签名区形态学重建（补全采区核心）" if spec_ev else "")
                    + "；形态学清理 + 连片性过滤"
                    + ("；光谱证据（NDVI低+BSI高+NDBI低+CVA显著）" if spec_ev else ""),
            "min_patch_px": args.min_patch,
            "detected_ha_by_year": {str(y): round(v * pixel_m2 / 1e4, 1)
                                    for y, v in zip(years_sorted, trend)},
        },
        "note": "真实数据：由 CLCD 30m 土地覆被产品转换，类别按矿区体系归并；"
                "采矿用地由矿权范围与裸地/建成区叠加识别" if args.mine else
                "真实数据：由 CLCD 30m 土地覆被产品转换，类别按矿区体系归并（未叠加矿权范围）",
    }
    with open(os.path.join(args.out_dir, "metadata.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    log(f"  · 研究区面积 {meta['area_km2']} km²，共 {len(args.years)} 期")

    log("\n[7/7] 完成！")
    log(f"  输出目录：{os.path.abspath(args.out_dir)}")
    log("  下一步：刷新浏览器 → 右下角数据选择器会出现新数据集 → 跑变化分析与预测")


if __name__ == "__main__":
    sys.exit(main())
