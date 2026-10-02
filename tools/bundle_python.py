# -*- coding: utf-8 -*-
# 矿地智预 MineGeoAI-Pre · by zhuoer mengzhuoda · 9.20
"""矿地智预 · 内置 Python 运行时打包

把当前解释器与项目所需依赖复制进发布目录的 runtime\\python\\，
使发布包【不依赖目标电脑上的 Python 环境】，拷过去双击即可运行。

只复制运行必需的包（白名单 + 自动带上 .dist-info），并清理
__pycache__ / 测试用例 / 示例数据，尽量压体积。

用法：
    python tools/bundle_python.py                      # 目标: 发布/矿地智预-v<版本>
    python tools/bundle_python.py --target <目录>       # 指定发布目录
    python tools/bundle_python.py --dry-run            # 只统计体积，不复制
"""
import argparse
import os
import shutil
import sys

# 项目直接依赖 + 传递依赖（按 import 名）
# 根依赖（其余传递依赖自动闭包解析，见 collect_closure）
PACKAGES = [
    # 直接依赖
    "fastapi", "uvicorn", "numpy", "scipy", "rasterio", "sklearn",
    "docx", "matplotlib", "PIL", "psutil",
    # fastapi / uvicorn 传递依赖
    "starlette", "pydantic", "pydantic_core", "annotated_types", "anyio",
    "sniffio", "idna", "typing_extensions", "click", "h11", "exceptiongroup",
    # rasterio / scipy / sklearn 传递依赖
    "affine", "click_plugins", "cligj", "snuggs", "certifi", "pyproj",
    "joblib", "threadpoolctl",
    # matplotlib 传递依赖
    "contourpy", "cycler", "fontTools", "kiwisolver", "pyparsing",
    "packaging", "six", "dateutil",
    # 其它可能被间接用到
    "requests", "urllib3", "charset_normalizer",
    # 本地小模型推理（AI 助手离线方案）：backend/core/llm.py 延迟导入，整个包约 10 MB，
    # 内置后目标电脑「把 GGUF 放进 models/ 就能用本地模型」，不必再装 C++ 编译环境。
    # 【必须写发行包名 llama-cpp-python】写导入名 llama_cpp 时 collect_closure 查不到元数据，
    # 依赖（diskcache / jinja2 / MarkupSafe）不会被带进来，打包后 import llama_cpp 直接失败。
    "llama-cpp-python",
]
# 解释器里要带的目录/文件（Lib 下只带标准库，不带 test/tkinter/idlelib/site-packages）
KEEP_TOP = ["python.exe", "pythonw.exe", "python311.dll", "python3.dll",
            "vcruntime140.dll", "vcruntime140_1.dll"]
SKIP_LIB_DIRS = {"test", "tests", "tkinter", "idlelib", "lib2to3", "site-packages",
                 "ensurepip", "distutils", "__pycache__", "venv"}
# 注意：不能剪 "testing"（numpy.testing 是可导入模块，sklearn 会用到）
SKIP_IN_PKG = {"__pycache__", "tests", "test", "docs", "doc", "examples",
               "example_data", "sample_data", "benchmarks"}


def collect_closure(roots: list) -> set:
    """用元数据自动解析依赖闭包（比手写清单可靠）

    手写白名单漏过 typing_inspection / annotated_doc 这类新传递依赖，
    导致打包后 fastapi、pydantic 导入失败——这里直接从已安装包的
    Requires-Dist 元数据递归展开。
    """
    import importlib.metadata as md
    want = {r.lower().replace("_", "-") for r in roots}
    seen, todo = set(), list(want)
    while todo:
        name = todo.pop()
        if name in seen:
            continue
        seen.add(name)
        try:
            reqs = md.requires(name) or []
        except Exception:
            continue
        for r in reqs:
            if ";" in r:                     # 环境标记：只取无条件的
                cond = r.split(";", 1)[1]
                if "extra" in cond:
                    continue
            base = r.split(";")[0].split("[")[0].strip()
            for sep in (">=", "==", "<=", "~=", "!=", ">", "<", " "):
                if sep in base:
                    base = base.split(sep)[0].strip()
            if base:
                todo.append(base.lower().replace("_", "-"))
    return seen


def dist_import_names(dist: str, site: str) -> list:
    """发行包名 → 实际导入名（优先读 top_level.txt，其次按名字猜）"""
    d = os.path.join(site, dist.replace("-", "_") + "-" )
    for e in os.listdir(site):
        if not e.endswith(".dist-info"):
            continue
        if e[:-len(".dist-info")].split("-")[0].lower().replace("_", "-") != dist:
            continue
        tl = os.path.join(site, e, "top_level.txt")
        if os.path.isfile(tl):
            names = [x.strip() for x in open(tl, encoding="utf-8") if x.strip()]
            if names:
                return names
        break
    return [dist.replace("-", "_")]


def pkg_dir(site: str, name: str):
    """定位包在 site-packages 中的实体（可能是目录或 .py 文件）"""
    d = os.path.join(site, name)
    if os.path.isdir(d):
        return d
    f = os.path.join(site, name + ".py")
    if os.path.isfile(f):
        return f
    return None


def copy_tree(src: str, dst: str, skip: set):
    """复制目录，跳过测试/缓存等，返回 (文件数, 字节数)"""
    n = size = 0
    for dp, dirs, files in os.walk(src):
        dirs[:] = [d for d in dirs if d.lower() not in skip]
        rel = os.path.relpath(dp, src)
        out = os.path.join(dst, rel) if rel != "." else dst
        os.makedirs(out, exist_ok=True)
        for fn in files:
            if fn.endswith((".pyc", ".pyo")) or fn.endswith(".pdb"):
                continue
            s = os.path.join(dp, fn)
            try:
                sz = os.path.getsize(s)
            except OSError:
                continue
            shutil.copy2(s, os.path.join(out, fn))
            n += 1
            size += sz
    return n, size


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", default=None)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if a.target:
        target = a.target
    else:
        import re
        ver = "1.0.0"
        with open(os.path.join(root, "backend", "main.py"), encoding="utf-8") as f:
            m = re.search(r'APP_VERSION\s*=\s*"([^"]+)"', f.read())
            if m:
                ver = m.group(1)
        target = os.path.join(root, "发布", "矿地智预-v" + ver)
    if not os.path.isdir(target):
        print("发布目录不存在：%s（先运行 tools/make_release.py）" % target)
        return 1

    py = sys.executable
    py_root = os.path.dirname(py)
    site = os.path.join(py_root, "Lib", "site-packages")
    rt = os.path.join(target, "runtime", "python")
    print("源解释器 : %s" % py)
    print("目标运行时: %s" % rt)

    total_n = total_b = 0
    plan = []
    # ① 解释器本体
    for name in KEEP_TOP:
        s = os.path.join(py_root, name)
        if os.path.isfile(s):
            plan.append((s, os.path.join(rt, name), set()))
    for name in ("DLLs",):
        s = os.path.join(py_root, name)
        if os.path.isdir(s):
            plan.append((s, os.path.join(rt, name), SKIP_IN_PKG))
    # Lib：标准库（去掉 test/tkinter/site-packages）
    s = os.path.join(py_root, "Lib")
    if os.path.isdir(s):
        plan.append((s, os.path.join(rt, "Lib"), SKIP_LIB_DIRS | SKIP_IN_PKG))
    for name in ("LICENSE.txt",):
        s = os.path.join(py_root, name)
        if os.path.isfile(s):
            plan.append((s, os.path.join(rt, name), set()))
    # ② 根依赖 + 自动闭包
    closure = collect_closure(PACKAGES)
    import_names = set()
    for dist in sorted(closure):
        for nm in dist_import_names(dist, site):
            import_names.add(nm)
    print("  依赖闭包：%d 个发行包 → %d 个导入名" % (len(closure), len(import_names)))
    # 所有 *.libs（wheel 自带的 DLL 目录，numpy.libs / scipy.libs 等，漏了会 DLL 加载失败）
    for e in sorted(os.listdir(site)):
        if e.endswith(".libs") and os.path.isdir(os.path.join(site, e)):
            import_names.add(e)
    for name in sorted(import_names):
        s = pkg_dir(site, name)
        if not s:
            print("  跳过（未安装）: %s" % name)
            continue
        d = os.path.join(rt, "Lib", "site-packages", os.path.basename(s))
        if os.path.isdir(s):
            plan.append((s, d, SKIP_IN_PKG))
        else:
            plan.append((s, d, set()))
    # ③ .dist-info（包元数据，pydantic/uvicorn 等会读）
    sp = os.path.join(rt, "Lib", "site-packages")
    for e in sorted(os.listdir(site)):
        if e.endswith(".dist-info") or e.endswith(".pth") or e.endswith(".pth.txt"):
            base = e.split("-")[0].lower().replace("_", "-")
            want = {p.lower().replace("_", "-") for p in PACKAGES}
            if base in want or e.endswith(".pth"):
                plan.append((os.path.join(site, e), os.path.join(sp, e), set()))

    for s, d, skip in plan:
        if os.path.isdir(s):
            n, b = copy_tree(s, d, skip) if not a.dry_run else (0, sum(
                os.path.getsize(os.path.join(dp, f)) for dp, ds, fs in os.walk(s)
                for f in fs if not f.endswith(".pyc")))
        else:
            n, b = 1, os.path.getsize(s)
            if not a.dry_run:
                os.makedirs(os.path.dirname(d), exist_ok=True)
                shutil.copy2(s, d)
        total_n += n
        total_b += b

    print("\n%s %d 个文件 · %.0f MB" % ("预计需复制" if a.dry_run else "已复制",
                                      total_n, total_b / 1024 ** 2))

    # ④ MSVC C++ 运行库（app-local 部署，微软允许随应用再分发）
    # 【为什么必须有】llama.cpp 的原生库（llama.dll / ggml*.dll）隐式依赖 MSVCP140.dll，
    # 而 python 自带的只有 vcruntime140（CPython 只用 C 运行库）。numpy/scipy/sklearn/rasterio
    # 之所以在没装 VC++ 运行库的电脑上也能跑，是因为它们的 wheel 在 *.libs 里各自带了一份
    # 改名版 msvcp140；llama_cpp 的 wheel 不带。于是漏了这一个 DLL 的表现就是——
    # 【其它功能全正常，只有 AI 助手的本地模型起不来】，而且开发机上装了 VS 永远不会暴露。
    msvc_dlls = ["msvcp140.dll", "vcomp140.dll",           # vcomp140 为 OpenMP 版 ggml-cpu 兜底
                 "msvcp140_1.dll", "msvcp140_2.dll",
                 "msvcp140_atomic_wait.dll", "concrt140.dll"]
    sys32 = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32")
    lib_dir = os.path.join(rt, "Lib", "site-packages", "llama_cpp", "lib")
    copied = []
    for name in msvc_dlls:
        src_dll = os.path.join(sys32, name)
        if not os.path.isfile(src_dll):
            continue
        # 放两处：解释器目录（app 目录，隐式依赖一定先搜这里）与 llama.dll 同目录（双保险）
        for dst_dir in (rt, lib_dir):
            if os.path.isdir(dst_dir):
                if not a.dry_run:
                    shutil.copy2(src_dll, os.path.join(dst_dir, name))
        copied.append(name)
    print("MSVC 运行库  : %s" % (("已随包携带 " + "、".join(copied)) if copied
                                 else "！源环境未找到 msvcp140.dll（目标机可能缺 VC++ 运行库）"))
    # ⑤ 多变体推理库的目录归位
    # 用 GGML_BACKEND_DL=ON + GGML_CPU_ALL_VARIANTS=ON 构建的 wheel，会把 ggml-cpu-*.dll
    # 装到 site-packages\bin\ 而不是 llama_cpp\lib\；而 Python 侧只认 llama_cpp\lib\。
    # 留在这里兜底：无论 wheel 装成什么样，进包之前都摆成"lib 里齐全"的样子。
    if not a.dry_run:
        sp_root = os.path.join(rt, "Lib", "site-packages")
        bin_dir = os.path.join(sp_root, "bin")
        lib_target = os.path.join(sp_root, "llama_cpp", "lib")
        if os.path.isdir(bin_dir) and os.path.isdir(os.path.dirname(lib_target)):
            moved = 0
            for f in os.listdir(bin_dir):
                if f.lower().endswith(".dll"):
                    shutil.copy2(os.path.join(bin_dir, f), os.path.join(lib_target, f))
                    moved += 1
            if moved:
                print("推理库归位  : 从 bin\\ 搬入 llama_cpp\\lib\\ 的原生库 %d 个（多变体构建）" % moved)

    # 断言式自检：llama.cpp 原生库依赖的这三个必须在【包内】，否则目标机没装 VC++ 运行库时
    # 只有 AI 助手会失败（开发机装了 VS，永远测不出来）
    need = ["msvcp140.dll", "vcruntime140.dll", "vcruntime140_1.dll"]
    lack = [d for d in need if not os.path.isfile(os.path.join(rt, d))]
    if lack:
        print("！原生依赖自检: 包内缺少 %s —— 目标电脑没装 VC++ 运行库时 AI 助手会起不来"
              % "、".join(lack))
    else:
        print("原生依赖自检: 本地模型所需的 MSVC 运行库均已在包内")

    if not a.dry_run:
        # 自愈式校验：用内置解释器逐个导入，缺什么就从源环境补什么（最多 5 轮）。
        # 手写清单与元数据闭包都可能漏（实测漏过 typing_inspection / annotated_doc /
        # attr(lxml) / numpy.libs），只有真跑一遍导入才能保证完整。
        import subprocess
        rt_py = os.path.join(rt, "python.exe")
        env = {k: v for k, v in os.environ.items() if not k.startswith("PYTHON")}
        env["PATH"] = "C:\\Windows\\system32;C:\\Windows"
        sp2 = os.path.join(rt, "Lib", "site-packages")
        # multipart 必须列上：fastapi 注册 Form/File 路由时才检查它，
        # 只 import fastapi 不报错，服务真启动才暴露（漏过，导致新机器起不来）
        # llama_cpp 也要列上：它是 AI 助手本地模型的推理库，延迟导入，
        # 只 import fastapi 之类根本碰不到它（漏过 diskcache/jinja2，打包后本地模型报错）
        roots = ["fastapi", "uvicorn", "numpy", "scipy", "rasterio", "sklearn",
                 "docx", "matplotlib", "PIL", "psutil", "multipart", "llama_cpp"]
        for rnd in range(5):
            fixed = 0
            for mod in roots:
                pr = subprocess.run([rt_py, "-c", "import " + mod], env=env, capture_output=True)
                if pr.returncode == 0:
                    continue
                txt = (pr.stdout + pr.stderr).decode("utf-8", "replace")
                miss = None
                for ln in txt.splitlines():
                    if "No module named" in ln:
                        miss = ln.split("'")[1].split(".")[0]
                if not miss:
                    print("  [警告] %s 导入失败（非缺模块）：%s"
                          % (mod, (txt.strip().splitlines() or ["?"])[-1][:100]))
                    continue
                src2 = pkg_dir(site, miss)
                if not src2:
                    print("  [警告] 源环境也没有 %s" % miss)
                    continue
                if os.path.isdir(src2):
                    n2, b2 = copy_tree(src2, os.path.join(sp2, os.path.basename(src2)), SKIP_IN_PKG)
                else:
                    os.makedirs(sp2, exist_ok=True)
                    shutil.copy2(src2, os.path.join(sp2, os.path.basename(src2)))
                    n2, b2 = 1, os.path.getsize(src2)
                total_n += n2
                total_b += b2
                fixed += 1
                print("  [补全] 缺少 %s → 已从源环境复制（%d 个文件）" % (miss, n2))
            if not fixed:
                # 只 import 不够：真正启动一次服务才算通过
                pr = subprocess.run([rt_py, "-c",
                                     "import sys;sys.path.insert(0,'backend');import main;"
                                     "print('SERVE_OK')"],
                                    cwd=os.path.dirname(rt), env=env, capture_output=True)
                txt = (pr.stdout + pr.stderr).decode("utf-8", "replace")
                if "SERVE_OK" in txt:
                    print("  完整性校验：依赖导入 + 服务可加载，全部通过（第 %d 轮）" % (rnd + 1))
                    break
                miss = None
                for ln in txt.splitlines():
                    if "No module named" in ln:
                        miss = ln.split("'")[1].split(".")[0]
                    if "python-multipart" in ln or "Form data requires" in ln:
                        miss = "multipart"
                if not miss:
                    print("  [警告] 服务加载失败：%s" % (txt.strip().splitlines() or ["?"])[-1][:120])
                    break
                src2 = pkg_dir(site, miss)
                if src2:
                    n2, b2 = (copy_tree(src2, os.path.join(sp2, os.path.basename(src2)), SKIP_IN_PKG)
                              if os.path.isdir(src2) else
                              (1, os.path.getsize(src2)))
                    if not os.path.isdir(src2):
                        shutil.copy2(src2, os.path.join(sp2, os.path.basename(src2)))
                    print("  [补全] 服务加载缺 %s → 已复制（%d 个文件）" % (miss, n2))
                    continue
    if not a.dry_run:
        print("运行时位置：%s" % rt)
        print("自检命令  ：\"%s\\python.exe\" -c \"import fastapi,rasterio,sklearn,matplotlib;print('ok')\""
              % rt)
    return 0


if __name__ == "__main__":
    sys.exit(main())
