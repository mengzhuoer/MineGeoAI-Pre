# -*- coding: utf-8 -*-
# 矿地智预 MineGeoAI-Pre · by zhuoer mengzhuoda · 9.20
"""
矿地智预 MineGeoAI-Pre - 新增检测区域数据自动下载

用途：给定研究区 AOI 与年份，自动完成：
  1. CLCD 土地覆被（Zenodo，窗口化 COG 只抓 AOI 范围）
  2. DEM（Copernicus GLO-30，AWS 公开数据，自动跨图幅拼接）

用法：
  python tools/download_area_data.py ^
    --aoi backend/data/aoi-平朔.geojson ^
    --years 2000 2005 2010 2015 2020 ^
    --clcd-out backend/data/clcd ^
    --dem-out backend/data/dem-平朔.tif

说明：
  · 自动读取 Windows 系统代理并传给 GDAL（GDAL 的 curl 不读系统代理，需显式设置）
  · 已存在的文件自动跳过（断点续传友好）
  · 输出命名与 import_real_dataset.py 的约定一致
"""
import argparse
import json
import os
import sys
import urllib.request

import numpy as np
import rasterio
from rasterio.crs import CRS
from rasterio.merge import merge
from rasterio.windows import from_bounds
from rasterio.warp import transform_bounds

ZENODO_RECORD = "8176941"        # CLCD 1985-2022（CC-BY-4.0）
DEM_BASE = "https://copernicus-dem-30m.s3.amazonaws.com"


_PROXY_URL = None


def setup_proxy():
    """探测系统代理并返回；GDAL 层用 CPL_CURL_PROXY 显式注入（不依赖环境变量）"""
    global _PROXY_URL
    proxies = urllib.request.getproxies()
    _PROXY_URL = proxies.get("https") or proxies.get("http") or None
    if _PROXY_URL:
        os.environ.setdefault("HTTP_PROXY", _PROXY_URL)
        os.environ.setdefault("HTTPS_PROXY", _PROXY_URL)
    os.environ.setdefault("CPL_VSIL_CURL_ALLOWED_EXTENSIONS", ".tif,content")
    os.environ.setdefault("GDAL_HTTP_MAX_RETRY", "6")
    os.environ.setdefault("GDAL_HTTP_RETRY_DELAY", "2")
    return _PROXY_URL


def gdal_env():
    """带代理配置的 GDAL 环境（rasterio.Env 上下文）"""
    opts = {"CPL_VSIL_CURL_ALLOWED_EXTENSIONS": ".tif,content",
            "GDAL_HTTP_MAX_RETRY": "6", "GDAL_HTTP_RETRY_DELAY": "2"}
    if _PROXY_URL:
        opts["CPL_CURL_PROXY"] = _PROXY_URL
    return rasterio.Env(**opts)


def _flatten(coords):
    """递归展平 GeoJSON 坐标嵌套 → 点列表"""
    if isinstance(coords[0], (int, float)):
        return [coords]
    out = []
    for c in coords:
        out.extend(_flatten(c))
    return out


def aoi_bounds_4326(aoi_path):
    with open(aoi_path, encoding="utf-8") as f:
        gj = json.load(f)
    feats = gj.get("features", [])
    geom = feats[0]["geometry"] if feats else gj
    pts = _flatten(geom["coordinates"])
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return (min(xs), min(ys), max(xs), max(ys))   # WGS84: left, bottom, right, top


def fetch_clcd_urls(years):
    """Zenodo API 查 CLCD 文件直链"""
    req = urllib.request.Request(f"https://zenodo.org/api/records/{ZENODO_RECORD}",
                                 headers={"User-Agent": "MineGeoAI-Pre/1.0"})
    data = json.loads(urllib.request.urlopen(req, timeout=60).read())
    out = {}
    for f in data.get("files", []):
        name = f.get("key", "")
        if name.endswith(".tif"):
            for y in years:
                if f"{y}" in name:
                    out[y] = f["links"]["self"]
    return out


def download_clcd(year, url, aoi, out_dir):
    out_path = os.path.join(out_dir, f"CLCD_v01_{year}_albert.tif")
    if os.path.isfile(out_path):
        print(f"  {year}: 已存在，跳过")
        return
    with gdal_env(), rasterio.open("/vsicurl/" + url) as src:
        fl, fb, fr, ft = transform_bounds("EPSG:4326", src.crs, *aoi)
        win = from_bounds(fl, fb, fr, ft, transform=src.transform).round_offsets().round_lengths()
        data = src.read(1, window=win)
        profile = src.profile.copy()
        profile.update(height=win.height, width=win.width,
                       transform=src.window_transform(win), compress="deflate")
        with rasterio.open(out_path, "w", **profile) as dst:
            dst.write(data, 1)
    print(f"  {year}: 完成 ({win.width}x{win.height})")


def dem_tile_urls(aoi):
    """AOI 覆盖的 1° 图幅列表（GLO-30 与 GLO-10 各一份）"""
    left, bottom, right, top = aoi
    lats = range(int(np.floor(bottom)), int(np.floor(top)) + 1)
    lons = range(int(np.floor(left)), int(np.floor(right)) + 1)
    tiles = []
    for lat in lats:
        for lon in lons:
            for res in ("30", "10"):
                t = f"Copernicus_DSM_COG_{res}_N{lat:02d}_00_E{lon:03d}_00_DEM"
                tiles.append(f"{DEM_BASE}/{t}/{t}.tif")
    return tiles


def download_dem(aoi, out_path):
    if os.path.isfile(out_path):
        print(f"  DEM: 已存在，跳过 ({out_path})")
        return
    tiles = dem_tile_urls(aoi)
    mems, ok = [], False
    for url in tiles:
        try:
            src = gdal_env().__enter__()
            src = rasterio.open("/vsicurl/" + url)
            fl, fb, fr, ft = transform_bounds("EPSG:4326", src.crs, *aoi)
            win = from_bounds(fl, fb, fr, ft, transform=src.transform).round_offsets().round_lengths()
            data = src.read(1, window=win)
            if data.size and np.isfinite(data).any() and (data > 0).sum() > data.size * 0.3:
                mems.append((data, src.window_transform(win), src.crs))
                src.close()
                ok = True
                break
            src.close()
        except Exception as e:
            print(f"  ! 图幅失败 {url.split('/')[-2]}: {str(e)[:60]}")
    if not ok:
        print("  ! DEM 下载失败（所有图幅不可用），请手动提供")
        return
    data, transform_, crs = mems[0]
    profile = dict(driver="GTiff", height=data.shape[0], width=data.shape[1],
                   count=1, dtype=data.dtype.name, crs=crs,
                   transform=transform_, compress="deflate")
    with rasterio.open(out_path, "w", **profile) as dst:
        dst.write(data, 1)
    print(f"  DEM: 完成 ({data.shape[1]}x{data.shape[0]}, "
          f"高程 {data[data > 0].min():.0f}~{data.max():.0f} m)")


def main():
    ap = argparse.ArgumentParser(description="矿地智预 · 新增区域数据自动下载")
    ap.add_argument("--aoi", required=True, help="研究区 GeoJSON（WGS84）")
    ap.add_argument("--years", nargs="+", type=int, required=True, help="年份，如 2000 2005 2010 2015 2020")
    ap.add_argument("--clcd-out", default="backend/data/clcd", help="CLCD 输出目录")
    ap.add_argument("--dem-out", required=True, help="DEM 输出文件（tif 路径）")
    args = ap.parse_args()

    setup_proxy()
    aoi = aoi_bounds_4326(args.aoi)
    print(f"AOI（WGS84）: lon {aoi[0]:.5f}~{aoi[2]:.5f}, lat {aoi[1]:.5f}~{aoi[3]:.5f}")

    os.makedirs(args.clcd_out, exist_ok=True)
    print("\n[1/2] CLCD 土地覆被（窗口化下载）…")
    try:
        urls = fetch_clcd_urls(args.years)
        for y in sorted(args.years):
            if y not in urls:
                print(f"  ! {y} 年文件未在 Zenodo 记录中找到")
                continue
            download_clcd(y, urls[y], aoi, args.clcd_out)
    except Exception as e:
        # Zenodo 在部分网络下被墙（DNS/连接失败）。CLCD 缺失不应阻断 DEM——
        # 开代理后重跑同一条命令即可续传（已下载文件自动跳过）
        print(f"  ! CLCD 下载失败（{type(e).__name__}: {e}）")
        print("  ! 该网络直连 Zenodo 不通：开代理后重跑本命令可续传；本次继续下载 DEM")

    print("\n[2/2] DEM（Copernicus GLO）…")
    download_dem(aoi, args.dem_out)

    print("\n完成。光谱指数仍需从 GEE 导出（见 docs/新增区域数据收集手册.md 第 2.2 节）。")


if __name__ == "__main__":
    sys.exit(main())
