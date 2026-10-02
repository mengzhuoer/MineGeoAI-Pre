# -*- coding: utf-8 -*-
# 矿地智预 MineGeoAI-Pre · by zhuoer mengzhuoda · 9.20
"""
矿地智预 - 平朔矿区示范数据集生成器
生成 5 期(2000/2005/2010/2015/2020)土地利用 GeoTIFF + 驱动因子栅格 + 元数据

类别编码（与软件约定一致）:
  1=耕地  2=林地  3=建设用地  4=采矿用地  5=水域  6=未利用地(排土场/裸地)

空间演化设计（符合露天煤矿真实规律）:
  2000      耕地/林地为基底，3 个小型采坑，沿河有带状水域
  2000-2010 采坑快速外扩（吞噬耕地/林地），前沿形成排土场(未利用地)，建设用地缓增
  2010-2015 采矿继续扩张但强度回落，老采坑核心区开始复垦为林地，采坑积水出现
  2015-2020 生态修复政策强化，复垦加速（林地+耕地回升），采矿面积趋稳
"""
import json
import os
import sys

import numpy as np
import rasterio
from rasterio.transform import from_origin
from rasterio.crs import CRS
from scipy import ndimage

# 命令行参数: python generate_pingshuo_dataset.py [seed] [数据集名]
SEED = int(sys.argv[1]) if len(sys.argv) > 1 else 42
DS_NAME = sys.argv[2] if len(sys.argv) > 2 else "pingshuo"
rng = np.random.default_rng(SEED)

SIZE = 256                      # 256x256 像素
RES = 30.0                      # Landsat 30m
PIXEL_AREA_M2 = RES * RES       # 900 m^2
X0, Y0 = 512000.0, 4370000.0    # UTM 49N，平朔安太堡矿区附近
CRS = CRS.from_epsg(32649)

CLASS_NAMES = ["耕地", "林地", "建设用地", "采矿用地", "水域", "未利用地"]
CLASS_IDS = [1, 2, 3, 4, 5, 6]
CLASS_COLORS = ["#f0c850", "#3e8e41", "#9b59b6", "#e74c3c", "#3f7fd4", "#d2b48c"]

YEARS = [2000, 2005, 2010, 2015, 2020]
OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "backend", "data", DS_NAME)


def fbm(shape=(SIZE, SIZE), octaves=5, seed=0, base_scale=8.0, persistence=0.55):
    """分形布朗运动噪声：产生自然地块的空间自相关场"""
    r = np.random.default_rng(seed)
    field = np.zeros(shape)
    amp, scale, total = 1.0, base_scale, 0.0
    for _ in range(octaves):
        field += amp * ndimage.gaussian_filter(r.standard_normal(shape), scale)
        total += amp
        amp *= persistence
        scale /= 2.0
    return field / total


def mode_filter(land: np.ndarray, size: int = 5) -> np.ndarray:
    """类别众数滤波：消除椒盐混杂像元，让地块连片（真实景观尺度）"""
    onehot = np.stack([(land == cid).astype(np.float32) for cid in CLASS_IDS])
    counts = np.stack([ndimage.uniform_filter(o, size) for o in onehot])
    return np.array(CLASS_IDS, dtype=np.uint8)[np.argmax(counts, axis=0)]


def init_base_landscape():
    """2000 年基底景观"""
    elev = 1350 + fbm(seed=1, base_scale=10) * 260          # DEM 1350-1610m
    moisture = fbm(seed=2, base_scale=12)                    # 湿度场

    # 河流：沿左下-右上的蜿蜒带
    yy, xx = np.mgrid[0:SIZE, 0:SIZE]
    river_path = (SIZE * 0.78) - 0.22 * SIZE * np.sin(xx / SIZE * 3.2 + 1.2)
    dist_river = np.abs(yy - river_path) / 6.0 + (fbm(seed=3, base_scale=6) * 2.0)
    river = dist_river < 1.0

    land = np.zeros((SIZE, SIZE), dtype=np.uint8)
    # 基底：谷地平缓→耕地，坡地→林地
    slope_proxy = np.abs(ndimage.sobel(elev, axis=0)) + np.abs(ndimage.sobel(elev, axis=1))
    flat = slope_proxy < np.quantile(slope_proxy, 0.45)
    land[flat] = 1                                          # 耕地
    land[~flat] = 2                                         # 林地
    # 湿度高的沟谷补林地，干燥塬面补未利用地
    dry = (moisture < np.quantile(moisture, 0.08)) & flat
    land[dry] = 6
    # 河流及河岸带
    land[river] = 5
    bank = (dist_river < 2.0) & (land != 5)
    land[bank] = 1
    # 村镇建设用地：4 个小居民点（河谷附近平地）
    towns = [(60, 70), (170, 55), (90, 195), (205, 170)]
    for ty, tx in towns:
        rr = 3 + int(rng.integers(0, 3))
        cvy, cvx = np.ogrid[:SIZE, :SIZE]
        dist_t = np.sqrt((cvy - ty) ** 2 + (cvx - tx) ** 2)
        blob = (dist_t < rr) & (land != 5)
        land[blob] = 3
    # 3 个初始小型采坑（排土场伴随）
    pits = [(150, 95, 4), (185, 130, 3), (130, 150, 3)]
    for py, px, pr in pits:
        cvy, cvx = np.ogrid[:SIZE, :SIZE]
        dist_p = np.sqrt((cvy - py) ** 2 + (cvx - px) ** 2)
        land[dist_p < pr] = 4
        land[(dist_p >= pr) & (dist_p < pr + 2) & (land != 5)] = 6
    land = mode_filter(land, 5)
    return land, elev


def evolve(land, phase):
    """按阶段演化一期。phase: 0=2000→2005, 1=2005→2010, 2=2010→2015, 3=2015→2020"""
    new = land.copy()
    yy, xx = np.mgrid[0:SIZE, 0:SIZE]
    # 矿带走向（西北-东南对角带）：越在带内采矿越易扩张
    belt = np.exp(-((yy - xx) ** 2) / (2 * 45 ** 2))

    # --- 阶段参数: (采坑扩张轮数, 扩张概率, 复垦强度, 建设用地增速) ---
    if phase == 0:
        rounds, grow_p, restore_rate, urban_p = 7, 0.72, 0.0, 0.10
    elif phase == 1:
        rounds, grow_p, restore_rate, urban_p = 9, 0.78, 0.0, 0.10
    elif phase == 2:
        rounds, grow_p, restore_rate, urban_p = 7, 0.65, 0.35, 0.06
    else:
        rounds, grow_p, restore_rate, urban_p = 5, 0.55, 0.55, 0.04

    # 1) 采坑扩张：直接外扩为采矿用地，坑缘生成排土场
    for _ in range(rounds):
        active = ndimage.binary_dilation(new == 4)
        edge = active & np.isin(new, [1, 2, 6])
        hit = (rng.random((SIZE, SIZE)) < grow_p * (0.35 + 0.65 * belt)) & edge
        new[hit] = 4
        # 新采坑外圈生成排土场（未利用地）：两层环带
        mine_d = ndimage.binary_dilation(new == 4)
        rim = mine_d & np.isin(new, [1, 2]) & ~hit
        new[rim & (rng.random((SIZE, SIZE)) < 0.55)] = 6
        rim2 = ndimage.binary_dilation(rim) & np.isin(new, [1, 2])
        new[rim2 & (rng.random((SIZE, SIZE)) < 0.30)] = 6

    # 2) 复垦：老矿内部（距矿缘深）→ 林地；排土场平台复垦为耕地
    mine_mask = new == 4
    if restore_rate > 0 and mine_mask.sum() > 20:
        depth = ndimage.distance_transform_edt(mine_mask)   # 矿内每点到非矿的距离
        thresh = np.quantile(depth[mine_mask], 0.35)
        old_core = mine_mask & (depth > thresh)
        restored = old_core & (rng.random((SIZE, SIZE)) < restore_rate)
        new[restored] = 2                                    # 复垦→林地
        dumps = ndimage.binary_dilation(new == 2) & (new == 6)
        new[dumps & (rng.random((SIZE, SIZE)) < restore_rate * 0.5)] = 1

    # 3) 建设用地缓慢增长（依附现有居民点和矿区服务区）
    urb = ndimage.binary_dilation(new == 3, iterations=1) & np.isin(new, [1, 6])
    new[urb & (rng.random((SIZE, SIZE)) < urban_p)] = 3

    # 4) 2010 起采坑最深处积水
    if phase >= 2:
        mine_mask = new == 4
        if mine_mask.sum() > 30:
            depth = ndimage.distance_transform_edt(mine_mask)
            deep = mine_mask & (depth > np.quantile(depth[mine_mask], 0.75))
            new[deep & (rng.random((SIZE, SIZE)) < 0.45)] = 5

    # 5) 林地自然扩散：缓慢侵占排土场边缘
    forest_edge = ndimage.binary_dilation(new == 2, iterations=1) & (new == 6)
    new[forest_edge & (rng.random((SIZE, SIZE)) < 0.04)] = 2

    return new


def write_tif(path, arr):
    profile = dict(
        driver="GTiff", height=SIZE, width=SIZE, count=1, dtype="uint8",
        crs=CRS, transform=from_origin(X0, Y0, RES, RES),
        compress="deflate", nodata=0,
    )
    with rasterio.open(path, "w", **profile) as dst:
        dst.write(arr.astype(np.uint8), 1)
        dst.set_band_description(1, "landuse_class")


def write_f32(path, arr):
    profile = dict(
        driver="GTiff", height=SIZE, width=SIZE, count=1, dtype="float32",
        crs=CRS, transform=from_origin(X0, Y0, RES, RES), compress="deflate",
    )
    with rasterio.open(path, "w", **profile) as dst:
        dst.write(arr.astype(np.float32), 1)


def area_stats(land):
    total = SIZE * SIZE
    return {CLASS_NAMES[i]: round(int((land == cid).sum()) * PIXEL_AREA_M2 / 10000.0, 1)
            for i, cid in enumerate(CLASS_IDS)}


def transition_matrix(a, b):
    m = np.zeros((6, 6), dtype=np.int64)
    for i, ci in enumerate(CLASS_IDS):
        for j, cj in enumerate(CLASS_IDS):
            m[i, j] = int(((a == ci) & (b == cj)).sum())
    return m


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    land, elev = init_base_landscape()

    slope = np.degrees(np.arctan(
        np.hypot(ndimage.sobel(elev / RES), ndimage.sobel(elev / RES))
    ))

    # 道路：一条主干道 + 连接矿区的支线（用于距离驱动因子）
    road = np.zeros((SIZE, SIZE), dtype=bool)
    yy, xx = np.mgrid[0:SIZE, 0:SIZE]
    main_y = 0.30 * SIZE + 18 * np.sin(xx / SIZE * 4.0)
    road[np.abs(yy - main_y) < 1.5] = True
    branch_x = 0.62 * SIZE + 14 * np.sin(yy / SIZE * 5.0)
    road[np.abs(xx - branch_x) < 1.2] = True
    road[140:150, 40:220] = road[140:150, 40:220] | True

    dist_road = ndimage.distance_transform_edt(~road) * RES          # 米
    dist_water = ndimage.distance_transform_edt(land != 5) * RES

    history = {}
    tms = {}
    for yi, year in enumerate(YEARS):
        if yi > 0:
            prev = land
            land = evolve(land, yi - 1)
            tms[f"{YEARS[yi-1]}-{year}"] = transition_matrix(prev, land).tolist()
        write_tif(os.path.join(OUT_DIR, f"landuse_{year}.tif"), land)
        history[str(year)] = area_stats(land)
        print(year, history[str(year)])

    # 驱动因子
    write_f32(os.path.join(OUT_DIR, "dem.tif"), elev)
    write_f32(os.path.join(OUT_DIR, "slope.tif"), slope)
    write_f32(os.path.join(OUT_DIR, "dist_road.tif"), dist_road)
    write_f32(os.path.join(OUT_DIR, "dist_water.tif"), dist_water)

    meta = {
        "region": f"山西省朔州市 · {DS_NAME} 矿区（合成示范）",
        "short_name": DS_NAME,
        "crs": "EPSG:32649 (UTM 49N)",
        "resolution_m": RES,
        "pixel_area_m2": PIXEL_AREA_M2,
        "extent": {
            "xmin": X0, "ymax": Y0,
            "xmax": X0 + SIZE * RES, "ymin": Y0 - SIZE * RES,
        },
        "geo": {"lon": 112.33, "lat": 39.40},
        "classes": [
            {"id": cid, "name": n, "color": c}
            for cid, n, c in zip(CLASS_IDS, CLASS_NAMES, CLASS_COLORS)
        ],
        "years": YEARS,
        "area_km2": round(SIZE * SIZE * PIXEL_AREA_M2 / 1e6, 2),
        "history": history,
        "transitions": tms,
        "note": "示范数据集：基于平朔矿区 2000-2020 Landsat 演化规律合成的空间自洽数据，用于系统演示与教学",
    }
    with open(os.path.join(OUT_DIR, "metadata.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    print("\nOK ->", os.path.abspath(OUT_DIR))
    print("总不像素面积 km2:", meta["area_km2"])
    for k, v in tms.items():
        print(k, "变化像元:", sum(sum(r) for i, r in enumerate(v)) - sum(v[i][i] for i in range(6)))


if __name__ == "__main__":
    main()
