# -*- coding: utf-8 -*-
# 矿地智预 MineGeoAI-Pre · by zhuoer mengzhuoda · 9.20
"""矿地智预 - 地理数据核心：数据集注册、栅格IO、专题地图渲染

多矿区数据集机制：backend/data/ 下每个含 metadata.json 的子目录即一个数据集，
当前会话使用哪个数据集由请求中间件通过 ContextVar 注入（并发安全），
新增矿区只需放入一个符合 schema 的文件夹，无需改代码。
"""
import contextvars
import io
import json
import os

import numpy as np
import rasterio
from PIL import Image, ImageDraw, ImageFont
from scipy import ndimage

DATA_ROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")

_active_dataset: contextvars.ContextVar = contextvars.ContextVar("active_dataset", default="pingshuo")

CLASS_META = [
    {"id": 1, "name": "耕地", "color": (240, 200, 80)},
    {"id": 2, "name": "林地", "color": (62, 142, 65)},
    {"id": 3, "name": "建设用地", "color": (155, 89, 182)},
    {"id": 4, "name": "采矿用地", "color": (231, 76, 60)},
    {"id": 5, "name": "水域", "color": (63, 127, 212)},
    {"id": 6, "name": "未利用地", "color": (210, 180, 140)},
]
CLASS_IDS = [c["id"] for c in CLASS_META]
CLASS_NAMES = [c["name"] for c in CLASS_META]
CLASS_RGB = np.array([c["color"] for c in CLASS_META], dtype=np.uint8)

_cache: dict = {}


def list_datasets() -> list:
    """扫描注册的所有矿区数据集"""
    out = []
    if not os.path.isdir(DATA_ROOT):
        return out
    for d in sorted(os.listdir(DATA_ROOT)):
        mp = os.path.join(DATA_ROOT, d, "metadata.json")
        if os.path.isfile(mp):
            try:
                with open(mp, encoding="utf-8") as f:
                    m = json.load(f)
                out.append({
                    "id": d,
                    "region": m.get("region", d),
                    "short_name": m.get("short_name", d),
                    "years": m.get("years", []),
                    "area_km2": m.get("area_km2"),
                    "resolution_m": m.get("resolution_m"),
                    "crs": m.get("crs", ""),
                    "note": m.get("note", ""),
                })
            except Exception:
                continue
    return out


def set_dataset(name: str):
    """切换当前数据集（无效名称抛异常）"""
    if not os.path.isfile(os.path.join(DATA_ROOT, name, "metadata.json")):
        raise ValueError(f"数据集不存在: {name}")
    _active_dataset.set(name)


def get_dataset() -> str:
    return _active_dataset.get()


def data_dir() -> str:
    return os.path.join(DATA_ROOT, _active_dataset.get())


def short_name() -> str:
    return dataset_meta().get("short_name", "平朔矿区")


def dataset_meta() -> dict:
    key = f"{get_dataset()}::meta"
    if key not in _cache:
        with open(os.path.join(data_dir(), "metadata.json"), encoding="utf-8") as f:
            _cache[key] = json.load(f)
    return _cache[key]


def load_landuse(year: int) -> np.ndarray:
    key = f"{get_dataset()}::lu_{year}"
    if key not in _cache:
        with rasterio.open(os.path.join(data_dir(), f"landuse_{year}.tif")) as src:
            _cache[key] = src.read(1)
    return _cache[key]


def load_driver(name: str) -> np.ndarray:
    key = f"{get_dataset()}::drv_{name}"
    if key not in _cache:
        with rasterio.open(os.path.join(data_dir(), f"{name}.tif")) as src:
            _cache[key] = src.read(1).astype(np.float32)
    return _cache[key]


def years() -> list:
    return dataset_meta()["years"]


def class_of_name(name: str) -> int:
    return CLASS_IDS[CLASS_NAMES.index(name)]


def name_of_class(cid: int) -> str:
    return CLASS_NAMES[CLASS_IDS.index(int(cid))]


def hillshade(dem: np.ndarray, azimuth=315.0, altitude=45.0, res=30.0) -> np.ndarray:
    """标准 Hillshade 计算"""
    dzdx = ndimage.sobel(dem, axis=1) / (8.0 * res)
    dzdy = ndimage.sobel(dem, axis=0) / (8.0 * res)
    slope = np.pi / 2.0 - np.arctan(np.hypot(dzdx, dzdy))
    aspect = np.arctan2(dzdx, dzdy)
    az, al = np.radians(azimuth), np.radians(altitude)
    shade = np.sin(al) * np.sin(slope) + np.cos(al) * np.cos(slope) * np.cos(az - aspect)
    return np.clip(shade, 0, 1)


def render_landuse_png(land: np.ndarray, shade: np.ndarray | None = None,
                       blend: float = 0.35, legend: bool = True, title: str | None = None,
                       scale: int = 1) -> bytes:
    """土地利用栅格 → 专题图 PNG（可选山体阴影融合）

    scale —— 整数最近邻放大倍数。原始栅格只有 272×330，投到大屏上会糊；
             最近邻不引入插值色带，地块边界保持锐利（类别图不能用双线性）。
    legend=False 且 title=None 时不留白、不画图例，输出与栅格严格按 scale 对齐，
             供交互地图图层叠加（没有留白，坐标换算是干净的）。
    """
    scale = max(1, int(scale))
    h, w = land.shape
    rgb = np.zeros((h, w, 3), dtype=np.float32)
    for i, cid in enumerate(CLASS_IDS):
        rgb[land == cid] = CLASS_RGB[i]

    if shade is not None:
        s = shade[..., None]
        rgb = rgb * (1.0 - blend + blend * (0.35 + 0.65 * s))

    if scale > 1:
        rgb = np.repeat(np.repeat(rgb, scale, axis=0), scale, axis=1)
    img = Image.fromarray(rgb.astype(np.uint8), "RGB")

    if legend or title:
        W, H = img.size
        m = 8 * scale
        pad_top = (38 if title else 8) * scale
        pad_bottom = (36 if legend else 8) * scale
        canvas = Image.new("RGB", (W + 2 * m, H + pad_top + pad_bottom), (250, 248, 241))
        canvas.paste(img, (m, pad_top))
        draw = ImageDraw.Draw(canvas)
        # 图版双框（测绘图集版式）
        draw.rectangle([6 * scale, 6 * scale, W + m + 1, pad_top + 1], outline=(194, 187, 166))
        draw.rectangle([7 * scale, pad_top - 1, W + m, pad_top], outline=(120, 130, 122))
        try:
            font = ImageFont.truetype("C:/Windows/Fonts/simhei.ttf", 14 * scale)
            font_s = ImageFont.truetype("C:/Windows/Fonts/simsun.ttc", 12 * scale)
        except OSError:
            font = font_s = ImageFont.load_default()
        if title:
            draw.text((12 * scale, 9 * scale), title, fill=(38, 50, 42), font=font)
        if legend:
            x = 10 * scale
            for i, c in enumerate(CLASS_META):
                draw.rectangle([x, pad_top + H + 10 * scale, x + 12 * scale, pad_top + H + 22 * scale],
                               fill=c["color"], outline=(120, 130, 122))
                draw.text((x + 16 * scale, pad_top + H + 8 * scale), c["name"], fill=(70, 82, 72), font=font_s)
                x += (16 + 12 * len(c["name"]) + 14) * scale
        img = canvas

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def render_hillshade_png(shade: np.ndarray, scale: int = 1) -> bytes:
    """山体阴影 → 灰度 PNG（交互地图底图）。连续量，用双线性放大更平滑。"""
    scale = max(1, int(scale))
    g = (np.clip(shade, 0, 1) * 255).astype("uint8")
    img = Image.fromarray(g, "L")      # 单通道灰度就够，PNG 体积约为 RGB 的三分之一
    if scale > 1:
        img = img.resize((img.size[0] * scale, img.size[1] * scale), Image.BILINEAR)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def render_change_png(before: np.ndarray, after: np.ndarray, shade=None) -> bytes:
    """变化检测图：未变化=淡化底色，变化像元=红色高亮，按转换类型着色条带"""
    h, w = before.shape
    rgb = np.full((h, w, 3), 235, dtype=np.float32)
    unchanged = before == after
    for i, cid in enumerate(CLASS_IDS):
        c = np.array(CLASS_RGB[i], dtype=np.float32)
        rgb[unchanged & (before == cid)] = c * 0.35 + 255 * 0.65
    changed = ~unchanged
    rgb[changed] = (214, 60, 45)
    if shade is not None:
        rgb[changed] = rgb[changed] * (0.55 + 0.45 * shade[changed, None])
    buf = io.BytesIO()
    Image.fromarray(rgb.astype(np.uint8), "RGB").save(buf, format="PNG")
    return buf.getvalue()


def render_heatmap_png(grid: np.ndarray, cmap="hot", label="") -> bytes:
    """连续值栅格（适宜性/概率/变化强度）→ 热力图 PNG"""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(5.2, 4.6), dpi=110)
    im = ax.imshow(grid, cmap=cmap, interpolation="nearest")
    ax.set_xticks([])
    ax.set_yticks([])
    cbar = fig.colorbar(im, ax=ax, fraction=0.046, pad=0.03)
    if label:
        cbar.set_label(label, fontsize=9)
    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight")
    plt.close(fig)
    return buf.getvalue()


def area_stats(land: np.ndarray, pixel_area_m2: float = 900.0) -> dict:
    total = land.size
    out = {"total_ha": round(total * pixel_area_m2 / 10000.0, 1), "classes": []}
    for i, meta in enumerate(CLASS_META):
        n = int((land == meta["id"]).sum())
        out["classes"].append({
            **meta,
            "pixels": n,
            "area_ha": round(n * pixel_area_m2 / 10000.0, 1),
            "percent": round(n / total * 100.0, 2),
        })
    return out


def transition_matrix(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """6x6 转移面积矩阵（像元数）: rows=from, cols=to"""
    m = np.zeros((6, 6), dtype=np.int64)
    for i, ci in enumerate(CLASS_IDS):
        for j, cj in enumerate(CLASS_IDS):
            m[i, j] = int(((a == ci) & (b == cj)).sum())
    return m
