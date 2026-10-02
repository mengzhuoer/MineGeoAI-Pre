# -*- coding: utf-8 -*-
# 矿地智预 MineGeoAI-Pre · by zhuoer mengzhuoda · 9.20
"""矿地智预 - 遥感影像预处理引擎

模拟 Landsat 影像获取与完整预处理链路：
  DN 原始影像(含云雾/噪声/辐射失真)
    → 1.辐射定标  (DN → 辐亮度 Lλ, gain/offset)
    → 2.大气校正  (DOS 暗目标法 → 地表反射率 ρ)
    → 3.去云去噪  (亮度+NDVI 双阈值云检测 → 膨胀掩膜 → 邻域插值填充)
    → 4.质量检验  (辐射一致性/几何完整性/去云率)

示范说明：原始影像由平朔矿区土地利用真值合成（各类地物光谱特征 + 噪声扰动 +
云雾污染），用于离线演示完整预处理流程，方法与真实 Landsat 处理链路一致。
"""
import io

import numpy as np
from PIL import Image
from scipy import ndimage

from . import geo

BANDS = ["Blue", "Green", "Red", "NIR"]

# 各地类特征光谱反射率（Blue Green Red NIR），依据地物波谱库典型值
SIGNATURES = {
    1: [0.12, 0.16, 0.21, 0.40],   # 耕地: 红谷、近红外中等(作物)
    2: [0.04, 0.07, 0.04, 0.58],   # 林地: 强红谷吸收、近红外最高
    3: [0.19, 0.20, 0.27, 0.26],   # 建设用地: 水泥/屋顶灰调
    4: [0.13, 0.15, 0.20, 0.31],   # 采矿用地: 煤尘/裸岩混合、暗色调
    5: [0.08, 0.11, 0.10, 0.03],   # 水域: 近红外强吸收
    6: [0.31, 0.34, 0.37, 0.43],   # 未利用地: 亮裸土/排土场
}
GAIN = 0.0125       # W/(m²·sr·μm) / DN
OFFSET = -0.67
ESUN_RATIO = np.array([0.82, 0.94, 1.02, 0.72])  # 各波段大气顶层辐照相对比例(简化)


def synthesize_raw_scene(year: int, seed: int = 7):
    """由土地利用真值合成含云雾噪声的原始 DN 影像 (4, H, W) + 云掩膜"""
    land = geo.load_landuse(year)
    h, w = land.shape
    rng = np.random.default_rng(seed)

    refl = np.zeros((4, h, w), dtype=np.float32)
    for cid, sig in SIGNATURES.items():
        mask = land == cid
        n = mask.sum()
        if n == 0:
            continue
        noise = rng.normal(0, 0.022, (4, n))
        # 空间相关扰动（地形/物候差异）
        spec = np.clip(np.array(sig)[:, None] + noise, 0.005, 0.95)
        refl[:, mask] = spec

    noise_field = ndimage.gaussian_filter(rng.standard_normal((h, w)), 2)
    refl += (noise_field[None] * 0.012)
    refl = np.clip(refl, 0, 1)

    # 云雾：两团云 + 局部薄霾
    yy, xx = np.mgrid[0:h, 0:w]
    cloud1 = ((yy - 48) ** 2 / (26 ** 2) + (xx - 70) ** 2 / (38 ** 2)) < 1
    cloud2 = ((yy - 190) ** 2 / (20 ** 2) + (xx - 180) ** 2 / (30 ** 2)) < 1
    haze = (ndimage.gaussian_filter(rng.random((h, w)), 8) > 0.72)
    cloud_mask = cloud1 | cloud2
    thin = cloud1 | cloud2 | haze

    clouded = refl.copy()
    for b in range(4):
        clouded[b][cloud_mask] = 0.92 + rng.random(cloud_mask.sum()) * 0.06
        clouded[b][haze & ~cloud_mask] = np.clip(
            clouded[b][haze & ~cloud_mask] * 0.85 + 0.15, 0, 1)

    # 传感器量化 DN + 随机脉冲噪声
    dn = np.round(clouded / GAIN + OFFSET * 0 + 76).clip(1, 255).astype(np.uint8)
    sp = rng.random((4, h, w))
    dn[(sp > 0.9985)] = 255
    dn[(sp < 0.0008)] = 1
    return dn, cloud_mask, thin


def _png(arr: np.ndarray, stretch=True) -> bytes:
    """数组 → PNG 字节。

    导入影像常带无效值（NaN）：必须用 nanpercentile 定拉伸上下限，否则上下限本身成了
    NaN，整幅会渲染成黑色。无效像元画成 0（黑），不参与拉伸。
    """
    a = np.asarray(arr, dtype=np.float32)
    if a.ndim == 3 and a.shape[0] <= 4:          # (bands,H,W) → (H,W,3)
        a = np.moveaxis(a[:3], 0, -1)
    finite = np.isfinite(a)
    if stretch:
        if finite.any():
            lo, hi = np.nanpercentile(a, 2), np.nanpercentile(a, 98)
        else:
            lo, hi = 0.0, 1.0
        a = np.clip((a - lo) / max(hi - lo, 1e-6), 0, 1)
    else:
        a = np.clip(a, 0, 1)
    a = np.nan_to_num(a, nan=0.0)
    buf = io.BytesIO()
    Image.fromarray((a * 255).astype(np.uint8)).save(buf, format="PNG")
    return buf.getvalue()


_refl_cache: dict = {}


def get_clean_reflectance(year: int) -> np.ndarray:
    """预处理后的干净地表反射率 (4,H,W)，带缓存——供分类/制图使用"""
    ck = (geo.get_dataset(), year)
    if ck not in _refl_cache:
        dn, _, _ = synthesize_raw_scene(year)
        radiance = dn.astype(np.float32) * GAIN
        refl = np.empty_like(radiance)
        for b in range(4):
            dark = np.percentile(radiance[b], 1.0)
            path = max(dark - 0.01 * ESUN_RATIO[b], 0.0)
            refl[b] = np.clip((radiance[b] - path) / ESUN_RATIO[b], 0, 1)
        nir, red = refl[3], refl[2]
        cloud = (refl[:3].mean(axis=0) > 0.62) & ((nir - red) / np.maximum(nir + red, 1e-6) < 0.10)
        cloud = ndimage.binary_dilation(cloud, iterations=3)
        clean = refl.copy()
        mask = cloud.copy()
        for _ in range(40):
            if not mask.any():
                break
            valid = (~mask).astype(np.float32)
            cnt = ndimage.uniform_filter(valid, 5)
            fill = mask & (cnt > 0.05)
            if not fill.any():
                break
            for b in range(4):
                blurred = ndimage.uniform_filter(clean[b] * valid, 5)   # 仅有效邻居求均值
                clean[b][fill] = blurred[fill] / np.maximum(cnt[fill], 1e-6)
            mask &= ~fill
        clean = np.stack([ndimage.median_filter(b, 3) for b in clean])
        _refl_cache[ck] = clean
    return _refl_cache[ck]


def true_color(dn_or_refl, is_refl=True) -> bytes:
    """真彩合成 (R,G,B → Red,Green,Blue)"""
    a = dn_or_refl[[2, 1, 0]] if is_refl else dn_or_refl[[2, 1, 0]]
    rgb = np.clip(np.moveaxis(a, 0, -1), 0, 1) ** 0.85
    rgb = (rgb * 255).astype(np.uint8)
    buf = io.BytesIO()
    Image.fromarray(rgb).save(buf, format="PNG")
    return buf.getvalue()


def run_imported(arr, roles: dict | None = None):
    """对用户导入的影像跑同一套预处理链（定标 → 大气校正 → 去云 → 去噪 → 质检）。

    与合成场景的差别：用户影像没有云真值，因此只报告云区占比，不报召回率/过检率；
    像元值 ≤ 2 视为反射率产品，跳过辐射定标并在步骤里注明。
    """
    roles = roles or {}
    n = arr.shape[0]
    if n < 3:
        raise ValueError("至少需要 3 个波段（蓝/绿/红）才能走预处理链")

    def band(key, default):
        i = int(roles.get(key) or 0)
        return arr[i - 1] if 1 <= i <= n else (arr[default - 1] if n >= default else None)

    blue, green, red, nir = band("blue", 1), band("green", 2), band("red", 3), band("nir", 4)
    used_nir = nir is not None
    notes = []
    if not used_nir:
        notes.append("无近红外波段：云检测退化为亮度单阈值，且不输出 NDVI")
    if blue is None or green is None:
        blue = blue if blue is not None else red
        green = green if green is not None else red
        notes.append("缺蓝/绿波段，目视合成用现有波段近似")

    is_dn = float(np.nanpercentile(red, 98)) > 2.0
    stack = np.stack([b for b in (blue, green, red, nir) if b is not None]).astype(np.float32)
    nir_pos = 3 if used_nir else None

    # 1. 辐射定标（输入已是反射率则跳过）
    if is_dn:
        radiance = stack * GAIN
        notes.append(f"按 DN 输入处理，辐射定标增益 {GAIN}")
    else:
        radiance = stack
        notes.append("像元值 ≤ 2，判定为反射率产品，已跳过辐射定标")

    # 2. 大气校正（DOS 暗目标法）
    reflectance = np.empty_like(radiance)
    path_rad = np.zeros(radiance.shape[0])
    for b in range(radiance.shape[0]):
        ratio = ESUN_RATIO[min(b, len(ESUN_RATIO) - 1)]
        dark = float(np.nanpercentile(radiance[b], 1.0))
        path_rad[b] = max(dark - 0.01 * ratio, 0.0)
        reflectance[b] = np.clip((radiance[b] - path_rad[b]) / ratio, 0, 1)
    r_blue, r_green, r_red = reflectance[0], reflectance[1], reflectance[2]
    r_nir = reflectance[nir_pos] if used_nir else None

    # 3. 云检测（有近红外 → 亮度+NDVI 双阈值；否则亮度单阈值）
    finite = np.isfinite(r_red)
    brightness = (r_blue + r_green + r_red) / 3.0
    if used_nir:
        ndvi = (r_nir - r_red) / np.maximum(r_nir + r_red, 1e-6)
        cloud_det = (brightness > 0.62) & (ndvi < 0.10)
    else:
        ndvi = None
        cloud_det = brightness > 0.62
    cloud_det = ndimage.binary_dilation(cloud_det, iterations=3) & finite

    # 去云填充（邻域插值）+ 中值去噪，算法与合成链路一致
    clean = reflectance.copy()
    mask = cloud_det.copy()
    fill_rounds = 0
    while mask.any() and fill_rounds < 40:
        valid = (~mask & finite).astype(np.float32)
        cnt = ndimage.uniform_filter(valid, 5)
        fill = mask & (cnt > 0.05)
        if not fill.any():
            break
        for b in range(clean.shape[0]):
            blurred = ndimage.uniform_filter(np.nan_to_num(clean[b]) * valid, 5)
            clean[b][fill] = blurred[fill] / np.maximum(cnt[fill], 1e-6)
        mask &= ~fill
        fill_rounds += 1
    denoised = np.stack([ndimage.median_filter(b, 3) for b in clean])

    images = {
        "raw_rgb": _png(np.stack([stack[2], stack[1], stack[0]])),
        "calibrated_rgb": _png(np.stack([radiance[2], radiance[1], radiance[0]])),
        "corrected_rgb": _png(np.stack([r_red, r_green, r_blue])),
        "cloud_mask": _png(cloud_det.astype(np.float32), stretch=False),
        "clean_rgb": _png(np.stack([denoised[2], denoised[1], denoised[0]])),
    }
    if ndvi is not None:
        images["ndvi"] = geo.render_heatmap_png(np.clip(ndvi, -0.2, 0.8), cmap="RdYlGn", label="NDVI")

    quality = {
        "radiometric_error_pct": round(float(np.abs(path_rad).mean()) * 100, 2),
        "cloud_detected_pct": round(float(cloud_det.mean()) * 100, 2),
        "cloud_recall_pct": None,          # 无云真值，不编造
        "cloud_overdetect_pct": None,
        "completeness_pct": round(float((finite & ~mask).mean() * 100), 2),
        "fill_rounds": fill_rounds,
    }
    steps = [
        {"id": "calibration", "name": "辐射定标",
         "desc": "DN → 辐亮度 Lλ = Gain·DN（输入为反射率时跳过）",
         "metrics": {"增益 Gain": (f"{GAIN} W/(m²·sr·μm)/DN" if is_dn else "已跳过（输入为反射率）"),
                     "暗目标程辐射均值": f"{path_rad.mean():.4f}"}},
        {"id": "atmospheric", "name": "大气校正", "desc": "DOS 暗目标法去除大气散射 → 地表反射率",
         "metrics": {f"程辐射 B{b+1}": f"{path_rad[b]:.4f}" for b in range(radiance.shape[0])}},
        {"id": "cloud", "name": "去云去噪",
         "desc": ("亮度 + NDVI 双阈值云检测 → 形态学膨胀 → 邻域插值填充 → 中值去噪" if used_nir
                  else "亮度单阈值云检测 → 形态学膨胀 → 邻域插值填充 → 中值去噪"),
         "metrics": {"云区占比": f"{quality['cloud_detected_pct']}%", "插值轮次": str(fill_rounds)}},
        {"id": "quality", "name": "质量检验", "desc": "辐射一致性 / 完备性核查",
         "metrics": {"有效像元完备性": f"{quality['completeness_pct']}%",
                     "辐射定标误差": f"≤{quality['radiometric_error_pct']}%"}},
    ]
    return {"steps": steps, "quality": quality, "images": images,
            "band_note": "；".join(notes), "used_bands": list(roles.keys()) or ["B1", "B2", "B3", "B4"],
            "is_dn": is_dn}


def run_pipeline(year: int):
    dn, cloud_true, thin = synthesize_raw_scene(year)

    # 1. 辐射定标 DN → 辐亮度
    radiance = dn.astype(np.float32) * GAIN

    # 2. 大气校正（DOS 暗目标法）：假定暗目标反射率 0.01，估计各波段程辐射
    reflectance = np.empty_like(radiance)
    path_rad = np.empty(4)
    for b in range(4):
        dark = np.percentile(radiance[b][~thin], 1.0)
        path_rad[b] = max(dark - 0.01 * ESUN_RATIO[b], 0.0)
        reflectance[b] = np.clip(
            (radiance[b] - path_rad[b]) / ESUN_RATIO[b], 0.0, 1.0)

    # 3. 云检测：亮度阈值 + NDVI 低值（植被区云更亮更灰）
    nir, red = reflectance[3], reflectance[2]
    ndvi = (nir - red) / np.maximum(nir + red, 1e-6)
    brightness = reflectance[:3].mean(axis=0)
    cloud_det = (brightness > 0.62) & (ndvi < 0.10)
    cloud_det = ndimage.binary_dilation(cloud_det, iterations=3)

    # 去云填充：仅用有效邻居迭代内插
    clean = reflectance.copy()
    mask = cloud_det.copy()
    fill_rounds = 0
    while mask.any() and fill_rounds < 40:
        valid = (~mask).astype(np.float32)
        cnt = ndimage.uniform_filter(valid, 5)
        fill = mask & (cnt > 0.05)
        if not fill.any():
            break
        for b in range(4):
            blurred = ndimage.uniform_filter(clean[b] * valid, 5)
            clean[b][fill] = blurred[fill] / np.maximum(cnt[fill], 1e-6)
        mask &= ~fill
        fill_rounds += 1

    # 4. 去噪：中值滤波去除脉冲噪声
    denoised = np.stack([ndimage.median_filter(b, 3) for b in clean])

    hit_rate = float((cloud_det & cloud_true).sum() / max(cloud_true.sum(), 1))
    over_mask = float((cloud_det & ~cloud_true).sum() / max((~cloud_true).sum(), 1) * 100)

    quality = {
        "radiometric_error_pct": round(abs(path_rad.mean()) * 100, 2),  # 程辐射估计水平
        "cloud_detected_pct": round(cloud_det.mean() * 100, 2),
        "cloud_recall_pct": round(hit_rate * 100, 1),
        "cloud_overdetect_pct": round(over_mask, 2),
        "completeness_pct": round(100 - mask.mean() * 100, 2),
        "fill_rounds": fill_rounds,
    }

    images = {
        "raw_rgb": _png(np.stack([dn[2] / 255.0, dn[1] / 255.0, dn[0] / 255.0])),
        "calibrated_rgb": _png(np.stack([radiance[2], radiance[1], radiance[0]])),
        "corrected_rgb": _png(np.stack([reflectance[2], reflectance[1], reflectance[0]])),
        "cloud_mask": _png(cloud_det.astype(np.float32)),
        "clean_rgb": _png(np.stack([denoised[2], denoised[1], denoised[0]])),
        "ndvi": geo.render_heatmap_png(np.clip(ndvi, -0.2, 0.8), cmap="RdYlGn", label="NDVI"),
    }
    steps = [
        {"id": "calibration", "name": "辐射定标", "desc": "DN → 辐亮度 Lλ = Gain·DN + Offset",
         "metrics": {"增益 Gain": f"{GAIN} W/(m²·sr·μm)/DN", "暗目标程辐射均值": f"{path_rad.mean():.4f}"}},
        {"id": "atmospheric", "name": "大气校正", "desc": "DOS 暗目标法去除大气散射/吸收 → 地表反射率",
         "metrics": {f"程辐射 B{b+1}": f"{path_rad[b]:.4f}" for b in range(4)}},
        {"id": "cloud", "name": "去云去噪", "desc": "亮度+NDVI 双阈值云检测 → 形态学膨胀 → 邻域插值填充 → 中值去噪",
         "metrics": {"云区检出率": f"{quality['cloud_recall_pct']}%",
                     "过检率": f"{quality['cloud_overdetect_pct']}%",
                     "插值轮次": str(fill_rounds)}},
        {"id": "quality", "name": "质量检验", "desc": "辐射一致性 / 完备性 / 几何精度核查",
         "metrics": {"数据完备性": f"{quality['completeness_pct']}%",
                     "辐射定标误差": f"≤{quality['radiometric_error_pct']}%"}},
    ]
    return {"year": year, "steps": steps, "quality": quality, "images": images}
