# -*- coding: utf-8 -*-
# 矿地智预 MineGeoAI-Pre · by zhuoer mengzhuoda · 9.20
"""导入影像检测：对用户自带影像（GeoTIFF / 普通图像）做检测，
   并与当前所选矿区数据库协同。

入口都是"用户影像 + 选定数据库"的组合，数据库提供三类东西：
  · 地类体系与阈值语境（扰动检测用）
  · 同网格的土地利用真值（分类模式当训练标签）
  · 驱动因子（分类模式当附加特征）

三种模式：
  disturb   光谱扰动检测：由影像自身波段算 NDVI/BSI/NDBI，自适应分位数阈值 +
            形态学清理 + 连片性过滤，检出裸土/扰动（采矿扰动候选）
  classify  数据库真值分类：影像对齐到数据库网格后，以数据库某年土地利用为标签
            训练随机森林并对影像分类，输出精度、混淆矩阵与分类图
  compare   与数据库对比：导入的是地类图（单波段类别值）时，与数据库某年做
            变化对比，复用变化分析引擎
"""
import io
import os

import numpy as np
import rasterio
from rasterio.enums import Resampling
from rasterio.warp import reproject, transform_bounds
from scipy import ndimage

from . import geo

# 无效值哨兵（GEE 导出常用 -9999，见 docs/路线A-真实数据接入指南.md）
NODATA_LIMIT = -9000.0
# 参与计算的最大边长：超大影像按比例降采样，避免一次塞满内存
MAX_SIDE = 1400

CLASS_EXT = {".tif", ".tiff", ".img", ".vrt", ".png", ".jpg", ".jpeg", ".bmp"}
RASTER_EXT = {".tif", ".tiff", ".img", ".vrt"}          # 视为地理栅格（可含投影/多波段）


def is_supported(name: str) -> bool:
    return os.path.splitext(name or "")[1].lower() in CLASS_EXT


# ---------------------------------------------------------------- 栅格探查
def _band_stats(arr: np.ndarray) -> dict:
    v = arr[np.isfinite(arr)]          # _read_preview 已把无效值置为 NaN
    if v.size == 0:
        return {"min": None, "max": None, "mean": None, "p2": None, "p98": None, "valid_pct": 0.0}
    return {
        "min": round(float(v.min()), 4), "max": round(float(v.max()), 4),
        "mean": round(float(v.mean()), 4),
        "p2": round(float(np.percentile(v, 2)), 4), "p98": round(float(np.percentile(v, 98)), 4),
        "valid_pct": round(float(v.size) / max(arr.size, 1) * 100, 1),
    }


def _read_preview(path: str, max_side: int = 320):
    """降采样读取整幅影像（探查用，快）"""
    with rasterio.open(path) as src:
        scale = max(src.width / max_side, src.height / max_side, 1.0)
        out = (max(1, int(src.height / scale)), max(1, int(src.width / scale)))
        arr = src.read(out_shape=(src.count, out[0], out[1]), resampling=Resampling.nearest)
    return _validify(arr.astype(np.float32))


def _validify(arr: np.ndarray) -> np.ndarray:
    arr = arr.astype(np.float32)
    arr[~np.isfinite(arr)] = np.nan
    arr[arr <= NODATA_LIMIT] = np.nan
    return arr


# 波段名 → 角色（GEE 导出常带波段描述，比按波段数猜可靠）
NAME_ROLE = [
    (("ndvi",), "ndvi"), (("ndbi",), "ndbi"), (("bsi",), "bsi"),
    (("ndwi",), "ndwi"), (("lst",), "lst"), (("temp",), "lst"),
    (("swir2",), "swir2"), (("swir1",), "swir"), (("swir",), "swir"),
    (("nir",), "nir"), (("red",), "red"), (("green",), "green"), (("blue",), "blue"),
    (("coastal",), "coastal"), (("pan",), "pan"),
]
# GEE 波段名（SR_B1…SR_B7 按 Landsat 8/9 OLI 解释）
GEE_B = {"sr_b1": "coastal", "sr_b2": "blue", "sr_b3": "green", "sr_b4": "red",
         "sr_b5": "nir", "sr_b6": "swir", "sr_b7": "swir2"}


def guess_kind(name: str, count: int, stats: list, preview: np.ndarray,
               band_names: list | None = None) -> dict:
    """推断影像类型与波段角色（前端可改）"""
    low = (name or "").lower()
    kind, roles_out, note = "unknown", {}, ""

    # ① 优先按波段名识别
    bn = [str(b).lower() for b in (band_names or [])]
    if bn and len(bn) == count:
        roles = {}
        for i, b in enumerate(bn):
            role = GEE_B.get(b)
            if role is None:
                for keys, r in NAME_ROLE:
                    if any(k in b for k in keys):
                        role = r
                        break
            if role:
                roles[i] = role
        idx_hit = sorted({r for r in roles.values() if r in ("ndvi", "bsi", "ndbi", "ndwi", "lst")})
        if len(idx_hit) == count and count >= 2:      # 整幅都是指数栈
            return {"kind": "indexstack",
                    "roles": {"index_keys": [roles[i] for i in range(count)]},
                    "note": f"按波段名判定为指数栈：{' / '.join(roles[i].upper() for i in range(count))}"}
        if len(idx_hit) == 1 and count == 1:
            return {"kind": "index", "roles": {"index": idx_hit[0]},
                    "note": f"按波段名判定为 {idx_hit[0].upper()} 单波段指数"}
        if roles:
            roles_out = {r: i + 1 for i, r in roles.items() if r not in ("swir2", "coastal", "pan")}
            if "swir2" in roles.values() and "swir" not in roles_out:
                roles_out["swir"] = [i + 1 for i, r in roles.items() if r == "swir2"][0]
            if roles_out.get("nir") and roles_out.get("red"):
                return {"kind": "multispectral", "roles": roles_out,
                        "note": "按波段名判定角色：" + " / ".join(f"{k}=B{v}" for k, v in roles_out.items())}

    if count >= 4:
        kind = "multispectral"
        if count >= 7:                      # Landsat 8/9 OLI：B1..B7
            roles_out = {"blue": 2, "green": 3, "red": 4, "nir": 5, "swir": 6}
            note = "按 7 波段 Landsat OLI（B1–B7）推断波段顺序"
        elif count == 6:                    # Landsat 5/7：B1..B5, B7
            roles_out = {"blue": 1, "green": 2, "red": 3, "nir": 4, "swir": 5}
            note = "按 6 波段 Landsat TM/ETM+（B1–B5, B7）推断波段顺序"
        else:                               # 4–5 波段：常见为 蓝/绿/红/近红外(+短波红外)
            roles_out = {"blue": 1, "green": 2, "red": 3, "nir": 4}
            if count >= 5:
                roles_out["swir"] = 5
            note = f"按 {count} 波段常见顺序（蓝/绿/红/近红外…）推断，请核对"
    elif count == 3:
        kind, roles_out = "rgb", {"blue": 3, "green": 2, "red": 1}
        note = "3 波段视为真彩色 RGB，无近红外，无法计算植被/裸土指数"
    elif count == 2:
        kind = "unknown"
        note = "2 波段无法判定，需手动指定哪个是近红外/短波红外"
    else:                                   # 单波段：指数或地类图
        for key, label in (("ndvi", "NDVI"), ("ndbi", "NDBI"), ("bsi", "BSI"),
                           ("ndwi", "NDWI"), ("lst", "LST")):
            if key in low:
                kind, roles_out, note = "index", {"index": key}, f"按文件名判定为 {label} 单波段指数"
                break
        if kind == "unknown":
            st = stats[0] if stats else {}
            vals = preview[0][np.isfinite(preview[0])] if preview.shape[0] else np.array([])
            uniq = np.unique(vals) if vals.size else np.array([])
            if (st.get("min") is not None and st["min"] >= 0 and st.get("max", 99) <= 9
                    and 0 < uniq.size <= 10 and np.allclose(uniq, np.round(uniq))):
                kind, note = "classmap", f"单波段整数取值 {sorted(int(u) for u in uniq)}，视为地类图"
            else:
                kind, note = "index", "单波段未识别为地类图，按指数处理（请在下方指定它是哪种指数）"
    return {"kind": kind, "roles": roles_out, "note": note}


def reference_grid(ds_id: str):
    """数据库参考网格（取其最后一期土地利用栅格）"""
    ys = json_years(ds_id)
    if not ys:
        return None
    p = os.path.join(geo.DATA_ROOT, ds_id, f"landuse_{ys[-1]}.tif")
    if not os.path.isfile(p):
        return None
    with rasterio.open(p) as d:
        return {"shape": (d.height, d.width), "crs": d.crs, "transform": tuple(d.transform)[:6],
                "bounds": tuple(d.bounds)}


def alignment_to_dataset(src, ds_id: str) -> dict:
    """判断影像与当前数据库网格的空间关系"""
    meta = reference_grid(ds_id)
    if not meta:
        return {"level": "unknown", "note": "无法读取数据库网格"}
    same_crs = (src.crs is not None and meta["crs"] is not None
                and src.crs.to_string() == meta["crs"].to_string())
    # 范围必须先换算到数据库坐标系再比较：不同投影的 bounds 直接比会误判为"不相交"
    if src.crs is not None and not same_crs:
        try:
            b = transform_bounds(src.crs, meta["crs"], *src.bounds)
        except Exception:
            b = src.bounds
    else:
        b = src.bounds
    db = meta["bounds"]
    overlap = not (b[2] <= db[0] or b[0] >= db[2] or b[3] <= db[1] or b[1] >= db[3])
    same_grid = same_crs and src.width == meta["shape"][1] and src.height == meta["shape"][0] \
        and all(abs(a - c) < 1e-6 for a, c in zip(tuple(src.transform)[:6], meta["transform"]))
    if same_grid:
        return {"level": "aligned", "note": "与数据库同一网格（可直接用数据库真值与驱动因子）"}
    if same_crs and overlap:
        return {"level": "same_crs", "note": "与数据库同投影且范围相交，将重采样到数据库网格后检测"}
    if overlap:
        return {"level": "need_reproject", "note": "与数据库投影不同但范围相交，将重投影到数据库网格"}
    return {"level": "disjoint", "note": "范围与数据库不相交，只能用影像自身信息检测"}


def json_years(ds_id: str) -> list:
    import json
    try:
        with open(os.path.join(geo.DATA_ROOT, ds_id, "metadata.json"), encoding="utf-8") as f:
            ys = json.load(f).get("years", [])
            return sorted(int(y) for y in ys if str(y).isdigit() or isinstance(y, int))
    except Exception:
        return []


def inspect(path: str, name: str) -> dict:
    """探查导入影像：波段/尺寸/投影/取值范围，与数据库的空间关系，波段角色推断"""
    ds_id = geo.get_dataset()
    with rasterio.open(path) as src:
        info = {
            "name": name, "bands": src.count, "width": src.width, "height": src.height,
            "crs": (src.crs.to_string() if src.crs else ""),
            "resolution_m": (round(abs(src.transform.a), 2) if src.transform else None),
            "dtype": src.dtypes[0], "driver": src.driver,
            "bounds": [round(v, 1) for v in src.bounds],
            "alignment": alignment_to_dataset(src, ds_id),
            "is_geo": bool(src.crs),
            # 波段名（GEE 等导出常带波段描述，是判断波段角色最可靠的线索）
            "band_names": [str(d) for d in (src.descriptions or []) if d],
        }
        prev = _read_preview(path)
    stats = [_band_stats(prev[i]) for i in range(prev.shape[0])]
    g = guess_kind(name, info["bands"], stats, prev, info["band_names"])
    info.update({"band_stats": stats, **g})
    info["dataset"] = {"id": ds_id, "region": geo.dataset_meta().get("region", ds_id),
                       "years": geo.years(), "classes": geo.CLASS_META}
    return info


# ---------------------------------------------------------------- 读取到数据库网格
def read_to_grid(path: str, dataset_id: str | None = None):
    """把影像读到（数据库）网格上：同网格直接读，同投影相交则对齐，异投影则重投影。
    返回 (数组 (bands,H,W) float32, 元信息)。数据库网格不存在时返回影像自身网格。"""
    ref = reference_grid(dataset_id or geo.get_dataset())
    if ref:
        ref = {**ref, "width": ref["shape"][1], "height": ref["shape"][0]}
    with rasterio.open(path) as src:
        if ref is None:                     # 无参考网格：按自身读取（必要时降采样）
            scale = max(src.width / MAX_SIDE, src.height / MAX_SIDE, 1.0)
            out = (max(1, int(src.height / scale)), max(1, int(src.width / scale)))
            arr = src.read(out_shape=(src.count, out[0], out[1]), resampling=Resampling.bilinear)
            return _validify(arr), {"grid": "image", "resampled": scale > 1.0,
                                    "pixel_m": round(abs(src.transform.a), 2)}

        need_warp = (src.crs is not None and src.crs.to_string() != ref["crs"].to_string()) \
            or src.width != ref["width"] or src.height != ref["height"] \
            or any(abs(a - c) > 1e-6 for a, c in zip(tuple(src.transform)[:6],
                                                      tuple(ref["transform"])[:6]))
        if not need_warp:
            arr = src.read()
            return _validify(arr), {"grid": "aligned", "resampled": False,
                                    "pixel_m": round(abs(src.transform.a), 2)}

        if src.crs is None:                 # 无投影信息：只做尺寸缩放对齐，不做几何配准
            arr = src.read(out_shape=(src.count, ref["height"], ref["width"]),
                           resampling=Resampling.bilinear)
            return _validify(arr), {"grid": "resized", "resampled": True,
                                    "pixel_m": round(abs(ref["transform"][0]), 2),
                                    "warn": "影像无投影信息，仅按尺寸缩放对齐，位置可能有偏差"}
        # 重投影到数据库网格
        dst = np.full((src.count, ref["height"], ref["width"]), np.nan, dtype=np.float32)
        for i in range(src.count):
            reproject(
                source=rasterio.band(src, i + 1), destination=dst[i],
                src_transform=src.transform, src_crs=src.crs,
                dst_transform=ref["transform"], dst_crs=ref["crs"],
                resampling=Resampling.bilinear, dst_nodata=np.nan,
            )
        return _validify(dst), {"grid": "warped", "resampled": True,
                                "pixel_m": round(abs(ref["transform"][0]), 2),
                                "src_crs": src.crs.to_string()}


# ---------------------------------------------------------------- 指数计算
def build_features(arr: np.ndarray, bands: dict, index_keys: list | None = None):
    """按波段映射计算指数特征。返回 ({指数名: 数组}, 说明) """
    def band(k):
        i = bands.get(k)
        return arr[i - 1] if i and 1 <= i <= arr.shape[0] else None

    feats, notes = {}, []
    if index_keys:                          # 用户直接指明每层是哪类指数（单波段/指数堆栈）
        for i, k in enumerate(index_keys):
            if i < arr.shape[0]:
                feats[k] = arr[i]
        return feats, "按用户指定的指数类型解读各波段"

    red, nir, swir, blue = band("red"), band("nir"), band("swir"), band("blue")
    if nir is not None and red is not None:
        feats["ndvi"] = (nir - red) / np.maximum(nir + red, 1e-6)
    if swir is not None and nir is not None:
        feats["ndbi"] = (swir - nir) / np.maximum(swir + nir, 1e-6)
    if swir is not None and red is not None and blue is not None:
        feats["bsi"] = ((swir + red) - (nir + blue)) / np.maximum((swir + red) + (nir + blue), 1e-6)
    elif swir is not None and red is not None:
        feats["bsi"] = (swir - red) / np.maximum(swir + red, 1e-6)
        notes.append("缺蓝光波段，BSI 用 (SWIR-Red)/(SWIR+Red) 近似")
    return feats, "；".join(notes)


# ---------------------------------------------------------------- 模式一：光谱扰动检测
QUANT = {"ndvi": ("<=", 25), "bsi": (">=", 65), "ndbi": ("<=", 80)}


def _clean_mask(mask: np.ndarray, close_it: int = 2, open_it: int = 1, min_patch: int = 20):
    """形态学清理 + 连片性过滤（滤掉零星误检）

    必须"先闭后开"：阈值的交并结果在像元级非常零碎（实测 4800 像元散成 1900 片），
    先闭运算把邻近碎斑并成片，再用开运算削掉孤立噪点；顺序反了会把整片检出抹平。
    """
    st = ndimage.generate_binary_structure(2, 1)
    if close_it > 0:
        mask = ndimage.binary_closing(mask, structure=st, iterations=close_it)
    if open_it > 0:
        mask = ndimage.binary_opening(mask, structure=st, iterations=open_it)
    lab, n = ndimage.label(mask)
    if n == 0:
        return mask, []
    sizes = ndimage.sum(mask, lab, range(1, n + 1))
    keep = np.zeros(n + 1, dtype=bool)
    keep[1:] = sizes >= min_patch
    mask = keep[lab]
    patches = []
    for i in np.argsort(-sizes)[:12]:
        if sizes[i] < min_patch:
            continue
        ys, xs = np.where(lab == i + 1)
        patches.append({"id": int(i + 1), "pixels": int(sizes[i]),
                        "area_ha": round(float(sizes[i]) * 0.09, 2),
                        "center_px": [int(xs.mean()), int(ys.mean())]})
    return mask, patches


def detect_disturbance(arr, bands, pixel_m, quant=None, close_it=2, open_it=1,
                       min_patch=20, index_keys=None):
    """光谱扰动检测：裸土/扰动（采矿扰动候选）

    每一层指数给出一条判据（自适应分位数阈值），取交集；
    缺哪层指数就少一条判据，并在结果里说明。
    """
    feats, note = build_features(arr, bands, index_keys)
    if not feats:
        raise ValueError("无法从该影像构造任何指数：需要近红外与红光波段，"
                         "或直接提供 NDVI/BSI/NDBI 指数栅格")
    q = dict(QUANT)
    for k, v in (quant or {}).items():
        if k in q and v:
            q[k] = (q[k][0], float(v))
    q["_close"], q["_open"] = close_it, open_it
    masks, used = [], []
    for k in ("ndvi", "bsi", "ndbi"):
        a = feats.get(k)
        if a is None:
            continue
        thr = float(np.nanpercentile(a, q[k][1]))
        if not np.isfinite(thr):
            continue
        op, _ = q[k]
        masks.append(a <= thr if op == "<=" else a >= thr)
        used.append({"index": k.upper(), "rule": f"{op} {round(thr, 4)}（{q[k][1]}% 分位）"})
    if not masks:
        raise ValueError("影像有效像元不足，无法计算自适应阈值")
    mask = masks[0]
    for m in masks[1:]:
        mask = mask & m
    mask = np.nan_to_num(mask, nan=False).astype(bool)
    valid = np.isfinite(arr[0])
    mask &= valid
    raw_pixels = int(mask.sum())
    mask, patches = _clean_mask(mask, close_it=int(q.get("_close", 2)),
                                open_it=int(q.get("_open", 1)), min_patch=min_patch)

    px_ha = (pixel_m ** 2) / 10000.0
    return {
        "method": "光谱扰动检测（自适应分位数阈值 + 形态学清理 + 连片性过滤）",
        "criteria": used, "index_note": note,
        "raw_pixels": raw_pixels,
        "raw_ha": round(raw_pixels * px_ha, 2),
        "disturb_pixels": int(mask.sum()),
        "disturb_ha": round(float(mask.sum()) * px_ha, 2),
        "disturb_percent": round(float(mask.sum()) / max(int(valid.sum()), 1) * 100, 2),
        "patch_count": len(patches), "patches": patches,
        "_mask": mask, "_feats": feats,
    }


def render_disturb_png(mask: np.ndarray, base: np.ndarray | None = None,
                       shade=None, title: str = "") -> bytes:
    """扰动检出图：底图为导入影像灰度或数据库地类淡化，检出像元红色高亮"""
    from PIL import Image, ImageDraw, ImageFont
    h, w = mask.shape
    if base is not None:
        lo, hi = np.nanpercentile(base, [2, 98])
        g = np.clip((base - lo) / max(hi - lo, 1e-6), 0, 1)
        gray = np.nan_to_num(g, nan=0.0)
        rgb = np.stack([gray, gray * 0.98, gray * 0.94], axis=-1).astype(np.float32)
    else:
        rgb = np.full((h, w, 3), 240.0, dtype=np.float32)
    if shade is not None:                   # 有数据库 DEM 时叠山体阴影，便于判读地形
        rgb = rgb * (0.55 + 0.45 * shade[..., None])
    rgb[mask] = (214, 60, 45)
    img = Image.fromarray(rgb.astype(np.uint8), "RGB")
    if title:
        canvas = Image.new("RGB", (w + 16, h + 54), (250, 248, 241))
        canvas.paste(img, (8, 30))
        d = ImageDraw.Draw(canvas)
        try:
            f = ImageFont.truetype("C:/Windows/Fonts/simhei.ttf", 14)
        except OSError:
            f = ImageFont.load_default()
        d.text((12, 8), title, fill=(38, 50, 42), font=f)
        d.rectangle([6, 6, w + 9, h + 33], outline=(194, 187, 166))
        d.text((12, h + 34), "红色 = 检出扰动像元（裸土/低植被高裸土指数）", fill=(70, 82, 72), font=f)
        img = canvas
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


# ---------------------------------------------------------------- 模式二：用数据库真值分类
def classify_with_dataset(arr, bands, year: int, use_drivers=True, train_ratio=0.35,
                          index_keys=None):
    """以数据库某年土地利用为训练标签，用导入影像（+数据库驱动因子）训练随机森林分类"""
    import sklearn.ensemble as ske
    from sklearn.metrics import cohen_kappa_score, confusion_matrix

    labels = geo.load_landuse(int(year))
    if labels.shape != arr.shape[1:]:
        raise ValueError(f"影像与数据库网格不一致：影像 {arr.shape[1:]} vs 数据库 {labels.shape}")
    feats, note = build_features(arr, bands, index_keys)
    feats = dict(feats)
    driver_names = []
    if use_drivers:                          # 数据库驱动因子参与分类（调用所选数据库）
        for k, nm in (("dem", "高程"), ("slope", "坡度"), ("dist_road", "距道路"), ("dist_water", "距水域")):
            try:
                feats[f"drv_{k}"] = geo.load_driver(k)
                driver_names.append(nm)
            except Exception:
                pass
    if not feats:
        raise ValueError("无法从该影像构造特征：请指定波段角色（至少红/近红外）或指数类型")
    names = list(feats.keys())
    X = np.stack([feats[k] for k in names], axis=-1).astype(np.float32)
    valid = np.isfinite(X).all(axis=2) & np.isfinite(labels) & (labels > 0)
    if valid.sum() < 200:
        raise ValueError(f"有效重叠像元仅 {int(valid.sum())} 个，不足以训练/检验")

    idx = np.flatnonzero(valid.ravel())
    rng = np.random.default_rng(7)
    Xf = X.reshape(-1, len(names))[idx]
    yf = labels.reshape(-1)[idx]
    tr, te = [], []
    for cid in geo.CLASS_IDS:               # 分层抽样（每类至少留 2 个测试样本）
        ci = np.flatnonzero(yf == cid)
        if ci.size < 4:
            tr.extend(ci.tolist())
            continue
        rng.shuffle(ci)
        k = max(2, min(int(ci.size * train_ratio), ci.size - 2))
        tr.extend(ci[:k].tolist())
        te.extend(ci[k:].tolist())
    if not tr or not te:
        raise ValueError("可用于训练/检验的样本不足")
    clf = ske.RandomForestClassifier(n_estimators=120, random_state=1, class_weight="balanced", n_jobs=-1)
    clf.fit(Xf[tr], yf[tr])
    pred_te = clf.predict(Xf[te])
    oa = float((pred_te == yf[te]).mean() * 100)
    try:
        kappa = float(cohen_kappa_score(yf[te], pred_te))
    except Exception:
        kappa = 0.0
    cm = confusion_matrix(yf[te], pred_te, labels=geo.CLASS_IDS).tolist()

    # 全图分类（仅有效像元）
    flat = X.reshape(-1, len(names))
    out = np.zeros(flat.shape[0], dtype=np.uint8)
    v = np.flatnonzero(valid.ravel())
    out[v] = clf.predict(flat[v]).astype(np.uint8)
    pred_map = out.reshape(labels.shape)
    pred_map[~valid] = 0
    per_class = []
    n_cls = len(geo.CLASS_IDS)
    for meta in geo.CLASS_META:
        i = geo.CLASS_IDS.index(meta["id"])          # 该地类在混淆矩阵中的行列号
        tp = cm[i][i]
        n_true = sum(cm[i])
        n_pred = sum(cm[r][i] for r in range(n_cls))
        per_class.append({**meta,
                          "producer_acc": round(tp / n_true * 100, 1) if n_true else None,
                          "user_acc": round(tp / n_pred * 100, 1) if n_pred else None,
                          "test_pixels": int(n_true)})
    return {
        "method": "随机森林（训练标签来自所选数据库的实测土地利用）",
        "label_year": int(year), "feature_names": names, "driver_names": driver_names,
        "index_note": note, "n_train": len(tr), "n_test": len(te),
        "overall_accuracy": round(oa, 2), "kappa": round(kappa, 4),
        "confusion_matrix": cm, "per_class": per_class,
        "_pred": pred_map,
    }


# ---------------------------------------------------------------- 模式三：与数据库对比
def class_values(a, class_map: dict | None = None):
    """栅格读数 → 数据库地类编号（0 = 无效/未映射），并校验取值合法性"""
    a = np.asarray(a, dtype=np.float32)
    v = np.isfinite(a)
    if class_map:                            # 用户给出"影像值 → 数据库地类 id"映射
        mapped = np.zeros(a.shape, dtype=np.uint8)
        for src_val, cid in class_map.items():
            mapped[(a == float(src_val)) & v] = int(cid)
    else:
        # 连续值栅格（NDVI/反射率等）不能当地类图：四舍五入后会被错当成 1–2 类
        vv = a[v]
        if vv.size and float((np.abs(vv - np.round(vv)) > 1e-6).mean()) > 0.01:
            raise ValueError("该影像为连续值栅格（指数/反射率等），不是地类图；"
                             "地类图的像元值应为整数 1–6")
        mapped = np.where(v, np.round(np.nan_to_num(a)), 0).astype(np.uint8)
    bad = sorted(set(np.unique(mapped)) - {0} - set(geo.CLASS_IDS))
    if bad:
        raise ValueError(f"影像取值 {bad} 不属于数据库地类体系 {geo.CLASS_IDS}；"
                         "请上传地类图（像元值 1–6），或提供取值映射")
    return mapped


def compare_with_dataset(arr, year: int, class_map: dict | None = None):
    """导入的地类图与数据库某年对比（转移矩阵 / 动态度 / 热点）"""
    from . import change
    mapped = class_values(arr[0], class_map)
    b = geo.load_landuse(int(year))
    if mapped.shape != b.shape:
        raise ValueError(f"影像与数据库网格不一致：影像 {mapped.shape} vs 数据库 {b.shape}")
    return change.analyze_arrays(mapped, b, "导入影像", f"{year} 年数据库")
