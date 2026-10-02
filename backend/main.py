# -*- coding: utf-8 -*-
# 矿地智预 MineGeoAI-Pre · by zhuoer mengzhuoda · 9.20
"""矿地智预 - 智慧地矿软件系统 FastAPI 服务

- 本地账号认证（SaaS 离线模式）：/api/* 需携带 Bearer Token（/api/auth/login 除外）
- 多矿区数据集：请求头 X-Dataset 选择数据集，默认第一个注册的数据集
"""
import hashlib
import json
import os
from functools import lru_cache
import sys
import time
import urllib.parse

sys.stdout.reconfigure(encoding="utf-8") if hasattr(sys.stdout, "reconfigure") else None

from fastapi import Body, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from core import (assistant, auth, change, classify, database, geo, importdetect, kb, llm,
                  messaging, predict, preprocess, report, viewer)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FRONTEND = os.path.join(ROOT, "frontend")

APP_VERSION = "1.2.0"          # 发布版本（前端从 /api/meta 取用并显示）

APP_AUTHOR = "by zhuoer mengzhuoda · 9.20"

app = FastAPI(title="矿地智预 MineGeoAI-Pre API", version=APP_VERSION,
              description=f"矿区土地利用智能预测系统后端 API · {APP_AUTHOR}",
              contact={"name": "zhuoer mengzhuoda"})

_requests_served = 0
_START_TS = __import__("time").time()

# CPU 采样：psutil.cpu_percent(interval=None) 返回"距上次调用"的占用率，
# 启动时先消耗一次 0 值样本
import psutil as _psutil
_psutil.cpu_percent(interval=None)


@app.get("/api/system/stats")
def api_system_stats():
    """控制中心：服务端运行状态（CPU/内存/磁盘/在线用户/请求数）"""
    import time as _time
    vm = _psutil.virtual_memory()
    du = _psutil.disk_usage(ROOT)
    proc = _psutil.Process()
    uptime = int(_time.time() - _START_TS)
    return {
        "cpu_percent": round(_psutil.cpu_percent(interval=None), 1),
        "mem": {
            "total_gb": round(vm.total / 1024 ** 3, 2),
            "used_gb": round(vm.used / 1024 ** 3, 2),
            "percent": round(vm.percent, 1),
        },
        "disk": {
            "total_gb": round(du.total / 1024 ** 3, 1),
            "used_gb": round(du.used / 1024 ** 3, 1),
            "percent": round(du.percent, 1),
        },
        "proc_mem_mb": round(proc.memory_info().rss / 1024 ** 2, 1),
        "uptime_s": uptime,
        "requests_served": _requests_served,
        "online_users": auth.count_online(),
        "users_total": len(auth.list_users()),
        "datasets": len(geo.list_datasets()),
        "engine": "CA-Markov + CLUE-S 融合模型 · 就绪",
    }


@app.middleware("http")
async def saas_middleware(request: Request, call_next):
    global _requests_served
    path = request.url.path
    # 数据集选择（多矿区支持）
    ds = request.headers.get("x-dataset")
    if ds:
        try:
            geo.set_dataset(urllib.parse.unquote(ds))
        except ValueError:
            pass  # 无效名称保持默认
    # 登录认证（除登录接口外所有 /api 均需 Token：Bearer 头 或 Cookie）
    if path.startswith("/api") and path != "/api/auth/login":
        header = request.headers.get("authorization", "")
        token = header[7:].strip() if header.lower().startswith("bearer ") else ""
        if not token:
            token = request.cookies.get("kdzy_token", "")
        user = auth.verify_token(token) if token else None
        if not user:
            return JSONResponse({"detail": "未登录或登录已过期"}, status_code=401)
        request.state.user = user
        auth.touch_session(token, user["username"])
    _requests_served += 1
    resp = await call_next(request)
    if not path.startswith("/api"):
        # 前端禁止启发式缓存：改前端后浏览器必须重新校验，否则用户会一直跑旧 app.js
        resp.headers["Cache-Control"] = "no-cache, must-revalidate"
    return resp


# ---------------- 认证接口 ----------------

@app.post("/api/auth/login")
def api_login(body: dict = Body(...)):
    user = auth.verify_login(str(body.get("username", "")), str(body.get("password", "")))
    if not user:
        raise HTTPException(401, "用户名或密码错误")
    token = auth.issue_token(user)
    resp = JSONResponse({"token": token, "user": user})
    # Cookie 供 <img>/<a> 等无法携带请求头的资源使用
    resp.set_cookie("kdzy_token", token, max_age=7 * 24 * 3600, path="/", samesite="lax")
    return resp


@app.post("/api/auth/logout")
def api_logout():
    resp = JSONResponse({"ok": True})
    resp.delete_cookie("kdzy_token", path="/")
    return resp


@app.get("/api/auth/me")
def api_me(request: Request):
    return {"user": request.state.user, "datasets": geo.list_datasets()}


@app.get("/api/auth/users")
def api_list_users(request: Request):
    if request.state.user.get("role") != "super":
        raise HTTPException(403, "仅超级管理员可查看")
    return {"users": auth.list_users()}


@app.post("/api/auth/users")
def api_create_user(request: Request, body: dict = Body(...)):
    """超级管理员创建用户"""
    if request.state.user.get("role") != "super":
        raise HTTPException(403, "仅超级管理员可创建用户")
    try:
        user = auth.create_user(
            str(body.get("username", "")).strip(),
            str(body.get("password", "")),
            str(body.get("role", "standard")),
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"user": user}


# ---------------- 用户数据：文件 / 偏好 / 历史 ----------------

def _user(request: Request) -> str:
    return request.state.user["username"]


def _quota(request: Request) -> int:
    return database.quota_bytes(request.state.user.get("role", "standard"))


@app.get("/api/files")
def api_files(request: Request, folder: str = "/"):
    u = _user(request)
    try:
        items = database.list_files(u, folder)
    except ValueError as e:
        raise HTTPException(400, str(e))
    for it in items:                       # 在线查看类型：image / text / other
        it["view"] = "" if it["is_dir"] else viewer.kind_of(it["name"])
    return {
        "folder": database.safe_folder(folder),
        "items": items,
        "used": database.used_bytes(u),
        "quota": _quota(request),
    }


@app.post("/api/files/upload")
async def api_files_upload(request: Request, folder: str = Form("/"), file: UploadFile = File(...)):
    u = _user(request)
    quota = _quota(request)
    used = database.used_bytes(u)
    orig = database.safe_name(file.filename or "未命名")
    folder = database.safe_folder(folder)
    disk_name = database.new_disk_name(orig)
    disk_path = os.path.join(database.get_user_dir(u), disk_name)
    size = 0
    try:
        with open(disk_path, "wb") as out:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if used + size > quota:
                    raise HTTPException(400, f"存储空间不足：每位用户配额 {quota // 1024**3} GB，请清理后重试")
                out.write(chunk)
    except HTTPException:
        os.remove(disk_path)
        raise
    file_id = database.add_file(u, folder, orig, size, file.content_type or "application/octet-stream", disk_name)
    return {"id": file_id, "name": orig, "size": size, "used": database.used_bytes(u), "quota": quota}


def _file_or_404(request: Request, file_id: int):
    """定位当前用户的文件，返回 (数据库记录, 磁盘路径)。"""
    u = _user(request)
    rec = database.get_file(u, file_id)
    if not rec:
        raise HTTPException(404, "文件不存在")
    path = os.path.join(database.get_user_dir(u), rec["disk_name"])
    if not os.path.isfile(path):
        raise HTTPException(404, "文件实体丢失")
    return rec, path


@app.get("/api/files/download/{file_id}")
def api_files_download(request: Request, file_id: int):
    rec, path = _file_or_404(request, file_id)
    return FileResponse(path, filename=rec["name"],
                        media_type=rec["mime"] or "application/octet-stream")


@app.get("/api/files/preview/{file_id}")
def api_files_preview(request: Request, file_id: int):
    """在线查看：以 inline 方式返回文件原件，供 <img> 等浏览器直接渲染。"""
    rec, path = _file_or_404(request, file_id)
    return FileResponse(path, media_type=viewer.media_type(rec["name"], rec["mime"]),
                        headers={"Content-Disposition": "inline"})


@app.get("/api/files/text/{file_id}")
def api_files_text(request: Request, file_id: int, encoding: str = ""):
    """文本文件在线查看/编辑：自动探测编码（UTF-8 / GB18030 / Big5）后返回正文。

    带 encoding 参数时按指定编码解码（用户手动纠正误判的编码）。
    """
    rec, path = _file_or_404(request, file_id)
    try:
        return viewer.read_text(path, rec["name"], rec["size"], encoding)
    except UnicodeDecodeError:
        raise HTTPException(400, "该编码无法解码此文件，请换一种编码")
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.post("/api/files/save")
def api_files_save(request: Request, body: dict = Body(...)):
    """保存在线编辑的文本内容。

    - 默认按文件原编码写回（GBK 文件不会被改成 UTF-8）；编码无法表示新字符时返回 code=encoding
    - base_sha256 为载入时的内容指纹，与磁盘不一致说明被其他会话改过，返回 409 由前端确认是否覆盖
    - 先写临时文件再原子替换，失败不会留下半截文件
    """
    u = _user(request)
    rec, path = _file_or_404(request, int(body.get("id", 0)))
    if viewer.kind_of(rec["name"]) != "text":
        raise HTTPException(400, "该文件类型不支持在线编辑")
    text = body.get("text")
    if not isinstance(text, str):
        raise HTTPException(400, "缺少文本内容")

    with open(path, "rb") as f:
        raw = f.read()
    if (body.get("base_sha256") and not body.get("force")
            and body["base_sha256"] != hashlib.sha256(raw).hexdigest()):
        raise HTTPException(409, "文件已被其他会话修改，请重新打开后再编辑")

    # 浏览器 textarea 的 value 一律是 LF，写回时按原文件的换行风格还原，
    # 避免保存一次就把 Windows 的 CRLF 文本全部改成 LF
    nl = raw.count(b"\n")
    if nl and raw.count(b"\r\n") * 2 >= nl:
        text = text.replace("\r\n", "\n").replace("\n", "\r\n")

    code = str(body.get("encoding") or "").strip()
    try:
        data = viewer.encode_text(text, code)
    except UnicodeEncodeError:
        label = viewer.CODEC_LABEL.get(code, "当前编码")
        return JSONResponse(status_code=400, content={
            "detail": f"{label} 无法表示输入中的部分字符", "code": "encoding",
        })
    except LookupError:
        raise HTTPException(400, "不支持的编码")

    delta = len(data) - int(rec["size"] or 0)
    if delta > 0 and database.used_bytes(u) + delta > _quota(request):
        raise HTTPException(400, "存储空间不足，无法保存")

    tmp = path + ".tmp"
    try:
        with open(tmp, "wb") as f:
            f.write(data)
        os.replace(tmp, path)                     # 同一分区内原子替换
    except OSError:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise HTTPException(500, "写入失败，原文件未被修改")

    ts = database.update_file_content(u, rec["id"], len(data))
    return {"ok": True, "id": rec["id"], "size": len(data), "modified": ts,
            "encoding": code or "utf-8", "bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
            "used": database.used_bytes(u), "quota": _quota(request)}


@app.post("/api/files/mkdir")
def api_files_mkdir(request: Request, body: dict = Body(...)):
    try:
        database.add_folder(_user(request), body.get("folder", "/"), database.safe_name(body.get("name", "新建文件夹")))
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"ok": True}


@app.post("/api/files/delete")
def api_files_delete(request: Request, body: dict = Body(...)):
    freed = database.delete_file(_user(request), int(body.get("id", 0)))
    return {"ok": True, "freed": freed, "used": database.used_bytes(_user(request)), "quota": _quota(request)}


@app.get("/api/user/prefs")
def api_get_prefs(request: Request):
    return {"prefs": database.get_prefs(_user(request))}


@app.post("/api/user/prefs")
def api_set_prefs(request: Request, body: dict = Body(...)):
    key = str(body.get("key", ""))[:40]
    if not key:
        raise HTTPException(400, "缺少 key")
    database.set_pref(_user(request), key, json.dumps(body.get("value"), ensure_ascii=False))
    return {"ok": True}


@app.get("/api/user/history")
def api_history(request: Request, limit: int = 8):
    return {"items": database.get_history(_user(request), limit)}


# ---------------- 系统状态 ----------------


# ---------------- 数据集与元数据 ----------------

@app.get("/api/datasets")
def api_datasets():
    return {"current": geo.get_dataset(), "datasets": geo.list_datasets()}


@app.get("/api/meta")
def api_meta():
    meta = geo.dataset_meta()
    return {
        "version": APP_VERSION,
        "author": APP_AUTHOR,
        "dataset_id": geo.get_dataset(),
        "dataset": meta,
        "datasets": geo.list_datasets(),
        "user_count": len(auth.list_users()),
        "scenarios": [
            {"id": k, "name": v["name"], "desc": v["desc"], "params": v["params"]}
            for k, v in predict.SCENARIOS.items()
        ],
        "param_labels": [
            {"key": k, "label": label, "desc": desc}
            for k, label, desc in predict.PARAM_LABELS
        ],
        "algorithms": [{"id": k, "name": v} for k, v in classify.ALGOS.items()],
        "templates": [{"id": k, "name": v["name"]} for k, v in report.TEMPLATES.items()],
        "stats": {str(y): geo.area_stats(geo.load_landuse(y)) for y in geo.years()},
    }


# ---------------- 结果图像仓库（确定性 key，重复运行自动覆盖） ----------------

IMG_STORE: dict = {}


def put_img(key: str, data: bytes) -> str:
    IMG_STORE[key] = data
    return f"/api/img/{key}"


def extract_images(images: dict, prefix: str) -> dict:
    out = {}
    for k, v in (images or {}).items():
        if isinstance(v, bytes):
            out[k] = put_img(f"{prefix}_{k}", v)
    return out


@app.get("/api/img/{key}")
def api_img(key: str):
    data = IMG_STORE.get(key)
    if data is None:
        raise HTTPException(404, "图像不存在")
    return Response(content=data, media_type="image/png")


# 地图渲染结果缓存：时间轴/地图会反复取同一张图，缓存掉"读栅格 + 算山体阴影"的开销
@lru_cache(maxsize=96)
def _map_png(kind: str, dataset: str, year: int, scale: int, plain: bool) -> bytes:
    shade = geo.hillshade(geo.load_driver("dem"))
    if kind == "hillshade":
        return geo.render_hillshade_png(shade, scale=scale)
    land = geo.load_landuse(year)
    if plain:      # 交互地图叠加：不留白、不画图例，与栅格严格对齐
        return geo.render_landuse_png(land, shade, legend=False, title=None, scale=scale)
    return geo.render_landuse_png(land, shade, legend=True,
                                  title=f"{geo.short_name()} {year} 年土地利用现状", scale=scale)


def _clamp_scale(v) -> int:
    try:
        return max(1, min(6, int(v or 1)))
    except (TypeError, ValueError):
        return 1


@app.get("/api/map/hillshade")
def api_map_hillshade(scale: int = 1):
    """山体阴影底图；scale 为整数放大倍数（原始栅格 256²，放大后仍清晰）"""
    png = _map_png("hillshade", geo.get_dataset(), 0, _clamp_scale(scale), False)
    return Response(content=png, media_type="image/png")


@app.get("/api/map/landuse/{year}")
def api_map_landuse(year: int, scale: int = 1, plain: int = 0):
    """土地利用专题图；plain=1 时不含图名与图例（交互地图叠加用）"""
    if year not in geo.years():
        raise HTTPException(404, f"无 {year} 年数据")
    png = _map_png("landuse", geo.get_dataset(), year, _clamp_scale(scale), bool(plain))
    return Response(content=png, media_type="image/png")


@app.get("/api/map/pick")
def api_map_pick(x: float, y: float, year: int = 0):
    """交互地图点击查询：UTM 坐标 → 该点地类（含该地类当年面积与占比）"""
    meta = geo.dataset_meta()
    ext, res = meta["extent"], float(meta["resolution_m"])
    if not (ext["xmin"] <= x <= ext["xmax"] and ext["ymin"] <= y <= ext["ymax"]):
        return {"inside": False, "x": round(x, 1), "y": round(y, 1)}
    ys = geo.years()
    year = year if year in ys else ys[-1]
    land = geo.load_landuse(year)
    h, w = land.shape
    col = min(w - 1, max(0, int((x - ext["xmin"]) / res)))
    row = min(h - 1, max(0, int((ext["ymax"] - y) / res)))
    stats = geo.area_stats(land, meta.get("pixel_area_m2", 900.0))
    cls = next((c for c in stats["classes"] if c["id"] == int(land[row, col])), None)
    return {
        "inside": True, "year": year, "row": row, "col": col,
        "x": round(x, 1), "y": round(y, 1),
        "class": cls["name"] if cls else "", "color": cls["color"] if cls else None,
        "class_area_ha": cls["area_ha"] if cls else None,
        "class_percent": cls["percent"] if cls else None,
        "total_ha": stats["total_ha"],
    }


@app.get("/api/stats")
def api_stats():
    return {str(y): geo.area_stats(geo.load_landuse(y)) for y in geo.years()}


@app.post("/api/preprocess")
def api_preprocess(request: Request, body: dict = Body(default={})):
    """预处理：默认跑所选数据库该年的合成场景；带 file_id 时对用户上传的影像跑同一套链路"""
    if body.get("file_id"):
        rec, path = _import_path(request, body)
        arr, grid = importdetect.read_to_grid(path)
        try:
            result = preprocess.run_imported(arr, body.get("bands") or {})
        except ValueError as e:
            raise HTTPException(400, str(e))
        result["images"] = extract_images(result["images"], f"prepimp{rec['id']}")
        result.update({"year": None, "source": "imported", "grid": grid,
                       "file": {"id": rec["id"], "name": rec["name"]}})
        database.add_history(_user(request), "数据预处理",
                             f"{rec['name']} · 云区 {result['quality']['cloud_detected_pct']}%")
        return result
    year = int(body.get("year", 2020))
    result = preprocess.run_pipeline(year)
    result["images"] = extract_images(result["images"], f"prep{year}")
    result["source"] = "database"
    return result


@app.post("/api/classify")
def api_classify(request: Request, body: dict = Body(...)):
    """分类：默认在所选数据库上做；带 file_id 时用导入影像做特征、数据库某年实测地类做标签"""
    if body.get("file_id"):
        rec, path = _import_path(request, body)
        arr, grid = importdetect.read_to_grid(path)
        year = int(body.get("year") or geo.years()[-1])
        try:
            r = importdetect.classify_with_dataset(
                arr, body.get("bands") or {}, year,
                use_drivers=bool(body.get("use_drivers", True)),
                train_ratio=float(body.get("train_ratio", 0.35)),
                index_keys=body.get("index_keys") or None)
        except Exception as e:
            raise HTTPException(400, str(e))
        pred = r.pop("_pred")
        r["map_url"] = put_img(f"classify_imp_{rec['id']}",
                               geo.render_landuse_png(pred, legend=True,
                                                      title=f"{rec['name']} 分类（标签来自 {geo.short_name()} "
                                                            f"{r['label_year']} 年实测）"))
        r["source"] = "imported"
        r["file"] = {"id": rec["id"], "name": rec["name"]}
        r["grid"] = grid
        r["algorithm_name"] = "随机森林（标签来自数据库实测地类）"
        database.add_history(_user(request), "分类分析",
                             f"{rec['name']} · OA {r['overall_accuracy']}%")
        return r
    year = int(body.get("year", 2020))
    algorithm = body.get("algorithm", "rf")
    train_ratio = float(body.get("train_ratio", 0.35))
    try:
        r = classify.classify(year, algorithm, train_ratio)
    except Exception as e:
        raise HTTPException(400, str(e))
    img_bytes = r.pop("prediction_map")
    r["map_url"] = put_img(f"classify_{year}_{algorithm}", img_bytes)
    r["source"] = "database"
    database.add_history(_user(request), "分类分析",
                         f"{r['algorithm_name']} · {year} 年 · OA {r['overall_accuracy']}%")
    return r


@app.post("/api/change")
def api_change(request: Request, body: dict = Body(...)):
    """变化分析：数据库两期，或导入地类图（可只给前期，也可两期都给）

    导入影像按所选数据库的网格对齐后再比较，因此结果与数据库结果可直接叠加判读。
    """
    b_year = int(body.get("b_year", 2020))
    file_a, file_b = body.get("file_a"), body.get("file_b")
    if file_a or file_b:
        try:
            if file_b:                                    # 两期都用导入影像
                rec_a, pa = _import_path(request, {"file_id": file_a})
                rec_b, pb = _import_path(request, {"file_id": file_b})
                A, ga = importdetect.read_to_grid(pa)
                B, gb = importdetect.read_to_grid(pb)
                va = importdetect.class_values(A[0])
                vb = importdetect.class_values(B[0])
                r = change.analyze_arrays(va, vb, rec_a["name"], rec_b["name"])
                r["grid"] = ga
                r["files"] = [{"id": rec_a["id"], "name": rec_a["name"]},
                              {"id": rec_b["id"], "name": rec_b["name"]}]
            else:                                          # 只给前期：与数据库某年对比
                rec_a, pa = _import_path(request, {"file_id": file_a})
                A, ga = importdetect.read_to_grid(pa)
                r = importdetect.compare_with_dataset(A, b_year,
                                                      class_map=body.get("class_map"))
                r["grid"] = ga
                r["files"] = [{"id": rec_a["id"], "name": rec_a["name"]}]
        except ValueError as e:
            raise HTTPException(400, str(e))
        r["map_url"] = put_img(f"change_imp_{r['a_year']}-{r['b_year']}", r.pop("change_map"))
        r["source"] = "imported"
        database.add_history(_user(request), "变化分析",
                             f"{r['a_year']}—{r['b_year']} · {r['changed_percent']}% 像元发生变化")
        return r
    a = int(body.get("a_year", 2000))
    if a not in geo.years() or b_year not in geo.years():
        raise HTTPException(400, "年份超出数据范围")
    r = change.analyze(a, b_year)
    img_bytes = r.pop("change_map")
    r["map_url"] = put_img(f"change_{a}_{b_year}", img_bytes)
    r["source"] = "database"
    database.add_history(_user(request), "变化分析",
                         f"{a}—{b_year} 年 · {r['changed_percent']}% 像元发生变化")
    return r


@app.post("/api/predict")
def api_predict(request: Request, body: dict = Body(...)):
    model = body.get("model", "ca-markov")
    a = int(body.get("a_year", 2000))
    b = int(body.get("b_year", 2020))
    target = int(body.get("target_year", 2030))
    scenario = body.get("scenario", "natural")
    params = body.get("params") or None
    if b not in geo.years() or a not in geo.years():
        raise HTTPException(400, "基准年份超出数据范围")
    if target <= b:
        raise HTTPException(400, "预测目标年份必须晚于基准期")
    try:
        if model == "clues":
            r = predict.run_clues(a, b, target, scenario, params)
        else:
            r = predict.run_ca_markov(a, b, target, scenario, params)
    except Exception as e:
        raise HTTPException(400, f"预测失败: {e}")
    r["images"] = extract_images(r.pop("images"), f"pred_{model}_{scenario}_{target}")
    r["model_name"] = "CA-Markov 融合模型" if model == "ca-markov" else "CLUE-S 模型"
    database.add_history(_user(request), "预测建模",
                         f"{r['model_name']} · {r['scenario_name']}情景 · 预测 {target} 年")
    return r


@app.post("/api/compare")
def api_compare(body: dict = Body(...)):
    a = int(body.get("a_year", 2000))
    b = int(body.get("b_year", 2020))
    target = int(body.get("target_year", 2030))
    r = predict.compare_scenarios(a, b, target)
    for item in r:
        item["image"] = put_img(f"cmp_{item['scenario']}_{target}", item.pop("image"))
    return {"base_year": b, "target_year": target, "scenarios": r,
            "base_stats": geo.area_stats(geo.load_landuse(b))}


@app.post("/api/validate")
def api_validate(request: Request, body: dict = Body(...)):
    """精度验证：默认用数据库该年实测地类；带 file_id 时用导入的实测地类图作真值"""
    train_a = int(body.get("train_a", 2000))
    train_b = int(body.get("train_b", 2005))
    target = int(body.get("target_year", 2010))
    scenario = body.get("scenario", "natural")
    truth = None
    truth_title = ""
    if body.get("file_id"):
        rec, path = _import_path(request, body)
        arr, _grid = importdetect.read_to_grid(path)
        try:
            truth = importdetect.class_values(arr[0], body.get("class_map"))
        except ValueError as e:
            raise HTTPException(400, str(e))
        truth_title = f"导入实测地类（{rec['name']}）"
    elif target not in geo.years():
        raise HTTPException(400, f"验证目标年 {target} 无实测数据，请上传该年的实测地类图")
    try:
        r = predict.validate((train_a, train_b), target, scenario, truth=truth,
                             truth_title=truth_title)
    except Exception as e:
        raise HTTPException(400, f"验证失败: {e}")
    r["images"] = extract_images(r.pop("images"), f"val_{train_a}_{train_b}_{target}")
    database.add_history(_user(request), "精度验证",
                         f"训练 {train_a}-{train_b} → 预测 {target} 年 · Kappa {r['kappa']}")
    return r


# ---------------- 导入影像检测（用户自带影像 + 所选数据库） ----------------

def _import_path(request: Request, body: dict):
    """取导入影像的磁盘路径：支持刚上传的个人文件（file_id）"""
    u = _user(request)
    rec = database.get_file(u, int(body.get("file_id", 0)))
    if not rec:
        raise HTTPException(404, "文件不存在，请先上传影像")
    if not importdetect.is_supported(rec["name"]):
        raise HTTPException(400, "仅支持 GeoTIFF / TIFF / IMG 等栅格与常见图像格式")
    rec2, path = _file_or_404(request, rec["id"])
    return rec2, path


@app.get("/api/image/inspect")
def api_image_inspect(request: Request, file_id: int):
    """探查导入影像：波段/尺寸/投影/取值范围 + 与当前数据库的空间关系 + 波段角色推断"""
    rec, path = _import_path(request, {"file_id": file_id})
    try:
        return importdetect.inspect(path, rec["name"])
    except Exception as e:
        raise HTTPException(400, f"影像读取失败：{e}")


@app.post("/api/image/detect")
def api_image_detect(request: Request, body: dict = Body(...)):
    """对导入影像运行检测（与当前所选数据库协同）

    输入不适用（如把地类图当扰动输入）或取值不合法时返回 400 并说明原因，不抛 500。
    """
    mode = str(body.get("mode") or "disturb")
    rec, path = _import_path(request, body)
    arr, grid = importdetect.read_to_grid(path)
    bands = body.get("bands") or {}          # {"red":3,"nir":4,"swir":5,...}
    index_keys = body.get("index_keys") or None
    pixel_m = float(grid.get("pixel_m") or 30.0)
    try:
        r = _run_image_mode(mode, arr, bands, index_keys, pixel_m, rec, body, grid)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except UnicodeDecodeError:
        raise HTTPException(400, "影像无法解析，请确认文件未损坏")
    r.update({"file": {"id": rec["id"], "name": rec["name"]}, "grid": grid,
              "dataset": {"id": geo.get_dataset(),
                          "region": geo.dataset_meta().get("region", geo.get_dataset())}})
    database.add_history(_user(request), r.pop("history_type"),
                         f"{rec['name']} · {r.pop('_detail')}")
    return r


def _run_image_mode(mode, arr, bands, index_keys, pixel_m, rec, body, grid):
    """按模式跑检测并组装结果（ValueError 由调用方转成 400）"""
    if mode == "disturb":
        r = importdetect.detect_disturbance(
            arr, bands, pixel_m, quant=body.get("quant"),
            close_it=int(body.get("close_it", 2)), open_it=int(body.get("open_it", 1)),
            min_patch=int(body.get("min_patch", 20)), index_keys=index_keys)
        mask = r.pop("_mask")
        feats = r.pop("_feats")
        base = feats.get("ndvi") if feats else None
        shade = None
        if grid["grid"] in ("aligned", "warped"):
            try:
                shade = geo.hillshade(geo.load_driver("dem"))
            except Exception:
                shade = None
        r["map_url"] = put_img(f"imp_disturb_{rec['id']}",
                               importdetect.render_disturb_png(
                                   mask, base=base, shade=shade,
                                   title=f"{rec['name']} 扰动检测（{geo.short_name()}）"))
        r["history_type"] = "影像扰动检测"
        r["_detail"] = f"扰动 {r['disturb_ha']} 公顷 · {r['patch_count']} 片"
    elif mode == "classify":
        r = importdetect.classify_with_dataset(
            arr, bands, int(body.get("year") or geo.years()[-1]),
            use_drivers=bool(body.get("use_drivers", True)),
            train_ratio=float(body.get("train_ratio", 0.35)), index_keys=index_keys)
        pred = r.pop("_pred")
        r["map_url"] = put_img(f"imp_classify_{rec['id']}",
                               geo.render_landuse_png(pred, legend=True,
                                                      title=f"{rec['name']} 分类（标签来自 {geo.short_name()} "
                                                            f"{r['label_year']} 年实测）"))
        r["history_type"] = "影像分类检测"
        r["_detail"] = f"OA {r['overall_accuracy']}% · Kappa {r['kappa']}"
    elif mode == "compare":
        r = importdetect.compare_with_dataset(
            arr, int(body.get("year") or geo.years()[-1]), class_map=body.get("class_map"))
        r["map_url"] = put_img(f"imp_compare_{rec['id']}-{r['b_year']}", r.pop("change_map"))
        r["history_type"] = "影像变化对比"
        r["_detail"] = f"变化 {r['changed_percent']}%"
    else:
        raise ValueError("未知的检测模式：%s" % mode)
    return r



# ---------------- AI 助手（本地模型优先，云端可切换） ----------------

@app.get("/api/llm/status")
def api_llm_status():
    """推理层现状：本地模型是否就绪 / 云端是否已配置 / 当前方案"""
    return llm.status()


@app.post("/api/llm/config")
def api_llm_config(body: dict = Body(default={})):
    """切换方案或填写云端参数（provider: local | api）"""
    return llm.save_config(body or {})


@app.get("/api/kb/stats")
def api_kb_stats():
    """知识库规模（设置页显示）"""
    return {**kb.stats(), "dir": os.path.relpath(kb.KB_DIR, ROOT)}


@app.post("/api/assistant/chat")
def api_assistant_chat(body: dict = Body(...)):
    """与 AI 助手对话：注入当前数据集事实清单，回答里带页面跳转标记"""
    try:
        r = assistant.ask(body.get("question", ""), body.get("history") or [])
    except llm.LLMError as e:
        raise HTTPException(503, str(e))
    except Exception as e:
        raise HTTPException(500, "助手调用失败：%s" % e)
    return r



# ---------------- 站内消息（私聊 + 系统通知） ----------------

@app.get("/api/msg/threads")
def api_msg_threads(request: Request):
    """会话列表：系统通知 + 与其他账号的会话（含未读数与在线状态）"""
    return {"threads": messaging.threads(_user(request))}


@app.get("/api/msg/directory")
def api_msg_directory(request: Request):
    """可对话账号（含在线状态），用于发起新会话"""
    return {"users": messaging.directory(_user(request))}


@app.get("/api/msg/search")
def api_msg_search(request: Request, q: str = ""):
    """搜索联系人（账号/角色）与消息内容；q 为空时返回空结果而不是报错"""
    return messaging.search(_user(request), q)


@app.get("/api/msg/thread/{peer}")
def api_msg_thread(request: Request, peer: str):
    try:
        return {"peer": peer, "messages": messaging.thread(_user(request), peer)}
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.post("/api/msg/send")
def api_msg_send(request: Request, body: dict = Body(...)):
    """发消息：普通账号只能私聊；超级管理员可发系统通知（群发）"""
    u = request.state.user
    to = str(body.get("to", "")).strip()
    is_super = u.get("role") == "super"
    kind = "notice" if (to == messaging.BROADCAST and is_super) else "chat"
    if to == messaging.BROADCAST and not is_super:
        raise HTTPException(403, "只有超级管理员可以发送系统通知")
    try:
        r = messaging.send(u["username"], to, str(body.get("body", "")), kind)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"ok": True, **r}


@app.get("/api/msg/unread")
def api_msg_unread(request: Request):
    """未读总数（Dock 角标用）"""
    return {"unread": messaging.unread_total(_user(request))}


@app.post("/api/report")
def api_report(request: Request, body: dict = Body(...)):
    template = body.get("template", "comprehensive")
    fmt = body.get("format", "docx")
    if template not in report.TEMPLATES:
        raise HTTPException(400, "未知报告模板")
    if fmt == "pdf":
        path = report.generate_pdf(template, body.get("options") or {})
    else:
        path = report.generate_docx(template, body.get("options") or {})
    database.add_history(_user(request), "报告生成",
                         f"{report.TEMPLATES[template]['name']}（{fmt.upper()}）")
    return {"filename": os.path.basename(path),
            "download_url": f"/api/report/download/{os.path.basename(path)}",
            "format": fmt}


@app.get("/api/report/list")
def api_report_list(request: Request):
    """历史报告列表（按时间倒序）"""
    items = []
    if os.path.isdir(report.REPORT_DIR):
        for fn in sorted(os.listdir(report.REPORT_DIR), reverse=True):
            p = os.path.join(report.REPORT_DIR, fn)
            if os.path.isfile(p):
                items.append({
                    "filename": fn,
                    "size_kb": round(os.path.getsize(p) / 1024, 1),
                    "time": time.strftime("%Y-%m-%d %H:%M", time.localtime(os.path.getmtime(p))),
                    "format": "pdf" if fn.lower().endswith(".pdf") else "docx",
                })
    return {"items": items}


@app.post("/api/report/delete")
def api_report_delete(request: Request, body: dict = Body(...)):
    fname = os.path.basename(str(body.get("filename", "")))
    path = os.path.join(report.REPORT_DIR, fname)
    if not os.path.isfile(path):
        raise HTTPException(404, "报告不存在")
    os.remove(path)
    return {"ok": True}


@app.get("/api/report/download/{fname}")
def api_report_download(fname: str):
    path = os.path.join(report.REPORT_DIR, fname)
    if not os.path.isfile(path):
        raise HTTPException(404, "报告不存在")
    media = "application/pdf" if fname.lower().endswith(".pdf") else \
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    return FileResponse(path, filename=fname, media_type=media)


app.mount("/", StaticFiles(directory=FRONTEND, html=True), name="frontend")


if __name__ == "__main__":
    import uvicorn
    # 默认只听本机；手机等局域网设备访问时用环境变量放开（如 set KDZY_HOST=0.0.0.0）
    _host = os.environ.get("KDZY_HOST", "127.0.0.1")
    _port = int(os.environ.get("KDZY_PORT", "8321"))
    if _host != "127.0.0.1":
        print(f"  ！注意：已监听 {_host}:{_port}（局域网内可访问），请确认已修改默认密码")
    uvicorn.run(app, host=_host, port=_port, log_level="info")   # info 才会记 uvicorn 访问日志（含客户端 IP），便于追溯演示访客
