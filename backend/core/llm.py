# -*- coding: utf-8 -*-
# 矿地智预 MineGeoAI-Pre · by zhuoer mengzhuoda · 9.20
"""矿地智预 · 大模型推理层（本地 / 云端两套方案，本地优先）

两套方案共用同一套调用协议，切换只改配置：
  · local —— 本地 GGUF 小模型（llama.cpp），离线可用、数据不出本机，默认方案
  · api   —— OpenAI 兼容接口（方舟 / DeepSeek / 通义等），需要 api_base + api_key

模型文件放在软件旁的 models/ 目录（不打进安装包），自动发现，优先 1.5B。
配置写在 backend/data/llm.json，首次调用时按默认值生成。

依赖说明：本地方案需要 llama-cpp-python（可选依赖）。没装、或没放模型时
本模块会明确报出原因，上层据此降级到模板/提示，绝不会抛未捕获异常。
"""
import json
import os
import threading
import time
import urllib.error
import urllib.request

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # backend/
ROOT = os.path.dirname(BASE_DIR)                                         # 项目根
MODEL_DIRS = [os.path.join(ROOT, "models"), os.path.join(BASE_DIR, "models")]
CONF_PATH = os.path.join(BASE_DIR, "data", "llm.json")

DEFAULT_CONF = {
    "provider": "local",          # local | api
    "local_model": "",            # 留空则自动在 models/ 里找
    "n_ctx": 4096,
    "threads": 0,                 # 0 = 用满 CPU 核数
    "max_tokens": 700,
    "temperature": 0.4,
    "api_base": "https://ark.cn-beijing.volces.com/api/v3",
    "api_key": "",
    "api_model": "",
    "timeout_s": 90,
}


class LLMError(Exception):
    """推理不可用或调用失败（消息面向用户，可直接展示）"""


def _explain_import_error(e: Exception) -> str:
    """把 llama_cpp 导入失败翻译成"照着做就能好"的中文说明

    两类原因表现完全不同，别混成一句话：
      · 真没装        → ModuleNotFoundError: No module named 'llama_cpp'
      · 装了但原生库加载不了（缺 MSVCP140.dll 等）→ ImportError: DLL load failed…
        这类在开发机上永远复现不了（装了 VS 就有运行库），一到干净电脑就
        表现为「其它功能都正常，只有 AI 助手不可用」。
    """
    msg = str(e)
    low = msg.lower()
    if isinstance(e, ModuleNotFoundError) or "no module named" in low:
        return ("未安装 llama-cpp-python（%s）。本地模型方案需要它："
                "用发布包（已内置）或 pip install llama-cpp-python。" % msg)
    if ("dll load failed" in low or "找不到指定的模块" in msg
            or "specified module could not be found" in low):
        return ("推理库已安装，但原生依赖加载失败（%s）。"
                "多半是这台电脑缺少 Microsoft VC++ 运行库 msvcp140.dll："
                "装一次「Microsoft Visual C++ 2015-2022 可再发行组件包」，"
                "或改用随包携带运行库的发布版（v1.1.0 起）。" % msg)
    return "本地推理库加载失败（%s）。" % msg


# 环境级原生故障：重试没有意义，必须直接翻译成能照着处理的说明
_NATIVE_FATAL = ("c000001d", "-1073741795", "illegal instruction",
                 "c0000005", "-1073741819", "access violation")


def _is_native_fatal(e: Exception) -> bool:
    low = str(e).lower()
    return any(k in low for k in _NATIVE_FATAL)


def _explain_native_error(e: Exception) -> str:
    """把推理时的原生崩溃翻译成人话（这类错误在开发机上永远复现不了）"""
    msg, low = str(e), str(e).lower()
    if any(k in low for k in ("c000001d", "-1073741795", "illegal instruction")):
        return ("这台电脑的 CPU 不支持推理库用到的指令集（Windows 报 0xC000001D 非法指令，"
                "通常是较老的 CPU 缺 AVX2/FMA）。两个办法：①「助手设置」里改用云端 API 方案；"
                "② 换用按通用指令集编译的推理库（打包时关掉 AVX2/FMA 即可）。（%s）" % msg)
    if any(k in low for k in ("c0000005", "-1073741819", "access violation")):
        return ("推理库访问了非法内存（0xC0000005），常见于 CPU 指令集不兼容或内存不足。"
                "可试用云端 API 方案。（%s）" % msg)
    return "本地推理失败：%s" % msg


_conf_cache = None
_llm = None
_lock = threading.Lock()
_last_err = ""     # 最近一次本地推理失败的原因："助手设置"里显示，省得只看到一句裸的 WinError


def _remember(msg: str):
    global _last_err
    _last_err = (msg or "")[:400]


def config() -> dict:
    global _conf_cache
    if _conf_cache is None:
        c = dict(DEFAULT_CONF)
        try:
            with open(CONF_PATH, encoding="utf-8") as f:
                c.update(json.load(f) or {})
        except Exception:
            os.makedirs(os.path.dirname(CONF_PATH), exist_ok=True)
            with open(CONF_PATH, "w", encoding="utf-8") as f:
                json.dump(c, f, ensure_ascii=False, indent=2)
        _conf_cache = c
    return _conf_cache


def save_config(patch: dict) -> dict:
    global _conf_cache, _llm
    c = dict(config())
    c.update({k: v for k, v in (patch or {}).items() if k in DEFAULT_CONF})
    os.makedirs(os.path.dirname(CONF_PATH), exist_ok=True)
    with open(CONF_PATH, "w", encoding="utf-8") as f:
        json.dump(c, f, ensure_ascii=False, indent=2)
    _conf_cache = None
    if patch.get("local_model") or patch.get("threads") or patch.get("n_ctx"):
        _llm = None            # 模型或推理参数变了，下次重新加载
    return config()


def find_local_model() -> str:
    """在 models/ 里找 GGUF：优先 1.5B，其次文件最大的那个"""
    hits = []
    for d in MODEL_DIRS:
        if not os.path.isdir(d):
            continue
        for fn in os.listdir(d):
            if fn.lower().endswith(".gguf"):
                p = os.path.join(d, fn)
                hits.append((os.path.getsize(p), p))
    if not hits:
        return ""
    prefer = [p for _, p in hits if "1.5b" in os.path.basename(p).lower()]
    if prefer:
        return prefer[0]
    return max(hits)[1]


def status() -> dict:
    """推理层现状：前端用它显示"本地/云端/未就绪"与原因"""
    c = config()
    model = c.get("local_model") or find_local_model()
    try:
        import llama_cpp            # noqa: F401
        lib_ok, lib_msg = True, ""
    except Exception as e:
        lib_ok, lib_msg = False, _explain_import_error(e)
    st = {
        "provider": c["provider"],
        "local": {
            "lib": lib_ok, "lib_msg": lib_msg,
            "model": os.path.basename(model) if model else "",
            "model_mb": round(os.path.getsize(model) / 1024 ** 2) if model else 0,
            "ready": bool(lib_ok and model),
            "loaded": _llm is not None,
            "last_error": _last_err,      # 上一次调用失败的原因（推理期崩溃在这里可查）
        },
        "api": {
            "configured": bool(c.get("api_key") and c.get("api_model")),
            "base": c.get("api_base", ""),
            "model": c.get("api_model", ""),
        },
    }
    if c["provider"] == "local" and not st["local"]["ready"]:
        st["hint"] = ("请把 GGUF 模型放到 %s（推荐 Qwen2.5-1.5B-Instruct Q4_K_M），"
                      "并安装 llama-cpp-python；或在配置里切换到 api 方案。"
                      % os.path.join(ROOT, "models"))
    elif c["provider"] == "api" and not st["api"]["configured"]:
        st["hint"] = "请先填写 api_key 与 api_model（火山方舟 / DeepSeek 等 OpenAI 兼容接口）"
    else:
        st["hint"] = ""
    return st


_backend_loaded = False


def _activate_cpu_backends():
    """让 ggml 扫描 llama_cpp\\lib\\ggml-cpu-*.dll，按 CPUID 自动挑最合适的一套 CPU 后端

    【为什么必须做】发布包里的推理库是"多变体"构建：同一个包里带 x64(SSE2 基线)、
    sse42、sandybridge(AVX)、haswell(AVX2)、skylakex/icelake/cascadelake(AVX-512) 等多套
    ggml-cpu-*.dll，由 ggml 在启动时按 CPU 支持情况挑一套。但 llama-cpp-python 自己
    不会调用这个加载器（它的 ctypes 封装只加载 llama.dll/ggml.dll），结果是——多变体一个都不注册，
    引擎找不到 CPU 后端，模型加载直接失败。

    早先的单变体构建没这个问题，代价是按本机 CPU 编译（AVX2/FMA），
    换到老 CPU 上就 0xC000001D 非法指令。所以这里补上这一步：
    新 CPU 全速，老 CPU 自动退到 x64 基线，两个坑一起解决。
    """
    global _backend_loaded
    if _backend_loaded:
        return
    _backend_loaded = True
    try:
        import llama_cpp
        from llama_cpp import _ggml
        libdir = os.path.join(os.path.dirname(llama_cpp.__file__), "lib")
        fn = getattr(_ggml.libggml, "ggml_backend_load_all_from_path", None)
        if fn is None or not os.path.isdir(libdir):
            return                     # 老的静态构建：CPU 后端已编在 ggml.dll 里，无需处理
        fn(libdir.encode("utf-8"))
    except Exception:
        # 加载器不可用不影响静态构建；真有问题会在后面载入模型时暴露
        pass


def _load_local(model: str):
    global _llm
    with _lock:
        if _llm is not None:
            return _llm
        try:
            from llama_cpp import Llama
        except Exception as e:
            raise LLMError("本地推理不可用：%s" % _explain_import_error(e))
        c = config()
        _activate_cpu_backends()          # 多变体推理库：先注册 CPU 后端再建模型
        try:
            _llm = Llama(
                model_path=model,
                n_ctx=int(c.get("n_ctx") or 4096),
                n_threads=int(c.get("threads") or os.cpu_count() or 4),
                verbose=False,
            )
        except Exception as e:
            # 载入阶段就可能撞上指令集不兼容（0xC000001D），必须翻译而不是原样抛出
            err = _explain_native_error(e) if _is_native_fatal(e) else "本地模型加载失败：%s" % e
            _remember(err)
            raise LLMError(err)
        return _llm


def _chat_local(messages, max_tokens, temperature):
    c = config()
    model = c.get("local_model") or find_local_model()
    if not model:
        raise LLMError("没有找到本地模型文件。请把 GGUF 放到 %s 目录（推荐 Qwen2.5-1.5B-Instruct Q4_K_M）"
                       % os.path.join(ROOT, "models"))
    llm = _load_local(model)
    try:
        out = llm.create_chat_completion(messages=messages, max_tokens=max_tokens,
                                         temperature=temperature, top_p=0.85,
                                         repeat_penalty=1.15, frequency_penalty=0.3)
        text = (out["choices"][0]["message"].get("content") or "").strip()
    except Exception as e1:
        # 原生环境级故障（指令集不兼容等）重试一次没有意义，直接翻译后抛出，
        # 否则用户看到的是一句裸的 [WinError -1073741795]，而且被当成"没带 chat 模板"再撞一次
        if _is_native_fatal(e1):
            err = _explain_native_error(e1)
            _remember(err)
            raise LLMError(err)
        try:
            # 少数 GGUF 没带 chat 模板，退回手工 Qwen 模板
            prompt = ""
            for m in messages:
                prompt += "<|im_start|>%s\n%s<|im_end|>\n" % (m["role"], m["content"])
            prompt += "<|im_start|>assistant\n"
            out = llm.create_completion(prompt=prompt, max_tokens=max_tokens,
                                        temperature=temperature, repeat_penalty=1.15)
            text = (out["choices"][0]["text"] or "").strip()
        except Exception as e2:
            err = (_explain_native_error(e2) if _is_native_fatal(e2)
                   else "本地推理失败：%s" % e2)
            _remember(err)
            raise LLMError(err)
    return text, os.path.basename(model)


def _chat_api(messages, max_tokens, temperature):
    c = config()
    if not (c.get("api_key") and c.get("api_model")):
        raise LLMError("api 方案未配置完整：需要 api_key 与 api_model")
    url = c["api_base"].rstrip("/") + "/chat/completions"
    body = json.dumps({"model": c["api_model"], "messages": messages,
                       "max_tokens": max_tokens, "temperature": temperature}).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST", headers={
        "Content-Type": "application/json", "Authorization": "Bearer " + c["api_key"]})
    try:
        with urllib.request.urlopen(req, timeout=int(c.get("timeout_s") or 90)) as r:
            d = json.loads(r.read())
        return d["choices"][0]["message"]["content"].strip(), c["api_model"]
    except urllib.error.HTTPError as e:
        detail = e.read()[:200].decode("utf-8", "replace")
        raise LLMError("云端接口返回 %s：%s" % (e.code, detail))
    except Exception as e:
        raise LLMError("云端接口调用失败：%s" % e)


def chat(messages, max_tokens=None, temperature=None) -> dict:
    """统一入口。返回 {text, provider, model, seconds, tokens}"""
    c = config()
    mt = int(max_tokens or c.get("max_tokens") or 700)
    tp = float(temperature if temperature is not None else c.get("temperature") or 0.4)
    t0 = time.time()
    if c.get("provider") == "api":
        text, model = _chat_api(messages, mt, tp)
    else:
        text, model = _chat_local(messages, mt, tp)
    return {"text": text, "provider": c.get("provider"), "model": model,
            "seconds": round(time.time() - t0, 1), "tokens": None}
