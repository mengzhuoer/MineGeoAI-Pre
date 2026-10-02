# -*- coding: utf-8 -*-
# 矿地智预 MineGeoAI-Pre · by zhuoer mengzhuoda · 9.20
"""矿地智预 · 启动引导（由 启动系统.bat 调用）

为什么启动逻辑放在 Python 里而不是批处理里：
  批处理文件里的中文在 GBK 控制台下会被 cmd 按字节解析，UTF-8 汉字的字节恰好落在
  GBK 的标点区间，`|` `&` `>` 会被当成分隔符，把命令行切碎（实测会报
  "'端口已在运行' 不是内部或外部命令"）。因此 .bat 只保留 ASCII，
  所有中文提示与判断逻辑放在这里——Python 写控制台走 UTF-16 接口，中文正常。

职责：检查依赖 → 缺则安装（官方源失败自动换清华镜像）→ 端口占用检查 →
      后台启动服务 → 等待就绪 → 打开浏览器；全过程写入「启动日志.txt」。
"""
import io
import os
import socket
import subprocess
import sys
import time
import webbrowser

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # 发布根目录
BACKEND = os.path.join(ROOT, "backend")
LOG = os.path.join(ROOT, "启动日志.txt")
PORT = 8321
DEPS = ["fastapi", "uvicorn", "numpy", "scipy", "rasterio", "sklearn",
        "docx", "matplotlib", "PIL", "psutil"]
MIRROR = "https://pypi.tuna.tsinghua.edu.cn/simple"

_logf = None


def log(msg: str):
    """同时写控制台与日志文件（日志固定 UTF-8，避免换机器后乱码）"""
    global _logf
    print(msg)
    if _logf is None:
        _logf = open(LOG, "a", encoding="utf-8")
    _logf.write(msg + "\n")
    _logf.flush()


def _open_browser(url: str):
    """打开浏览器；服务器专版设 KDZY_NO_BROWSER=1 时跳过（云服务器没有桌面会话）"""
    if os.environ.get("KDZY_NO_BROWSER"):
        return
    webbrowser.open(url)


def port_busy(port: int = PORT) -> bool:
    with socket.socket() as s:
        s.settimeout(0.6)
        return s.connect_ex(("127.0.0.1", port)) == 0


def wait_enter():
    try:
        input("\n按回车键关闭本窗口…")
    except (EOFError, KeyboardInterrupt):
        pass


def missing_deps() -> list:
    import importlib.util
    return [m for m in DEPS if importlib.util.find_spec(m) is None]


def install_deps() -> bool:
    req = os.path.join(ROOT, "requirements.txt")
    log("  [1/3] 缺少运行依赖：" + ", ".join(missing_deps()))
    log("        开始安装（首次约 3-10 分钟，请勿关闭窗口）…")
    for idx, extra in enumerate(([], ["-i", MIRROR])):
        cmd = [sys.executable, "-m", "pip", "install", "-r", req] + extra
        if idx:
            log("        直连官方源失败，改用清华镜像重试…")
        try:
            p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            tail = p.stdout.decode("utf-8", "replace").strip().splitlines()[-3:]
            for line in tail:
                log("        " + line[:160])
            if p.returncode == 0 and not missing_deps():
                return True
        except Exception as e:
            log("        安装异常：" + str(e))
    return False


def main() -> int:
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    with open(LOG, "w", encoding="utf-8") as f:
        f.write("===== 矿地智预启动记录 %s =====\n" % time.strftime("%Y-%m-%d %H:%M:%S"))
    _logf = None  # 让 log() 以追加方式重开

    log("=" * 52)
    log("   矿地智预 MineGeoAI-Pre")
    log("   by zhuoer mengzhuoda · 9.20")
    log("   矿区土地利用智能预测系统 · FastAPI + Vue3")
    log("=" * 52)
    bundled = os.sep + "runtime" + os.sep in os.path.abspath(sys.executable)
    log("  Python %s（%s）" % (sys.version.split()[0],
                              "内置运行时，无需外部环境" if bundled else "系统安装的 Python"))
    log("  解释器 %s" % sys.executable)
    log("  日志    %s" % LOG)

    if bundled:
        log("  [1/3] 使用内置运行时，跳过依赖检查")
    if sys.version_info < (3, 10):
        log("\n[错误] 需要 Python 3.10 及以上（当前 %s）。" % sys.version.split()[0])
        log("       请到 https://www.python.org/downloads/ 安装新版后重试。")
        wait_enter()
        return 1

    if not os.path.isfile(os.path.join(BACKEND, "main.py")):
        log("\n[错误] 找不到 backend\\main.py —— 请确认整个文件夹一起拷贝/解压，")
        log("       不要把 .bat 单独拿出来运行。")
        wait_enter()
        return 1

    miss = [] if bundled else missing_deps()
    if miss:
        if not install_deps():
            log("")
            log("[错误] 依赖安装失败。可尝试：")
            log("       ① 用手机热点联网后重新双击「启动系统.bat」")
            log("       ② 或在有网的电脑上执行  pip download -r requirements.txt -d wheels")
            log("          把 wheels 目录一起拷来，再执行")
            log("          pip install --no-index --find-links=wheels -r requirements.txt")
            log("       ③ 详细报错见本目录「启动日志.txt」")
            wait_enter()
            return 1
    else:
        log("  [1/3] 运行依赖已就绪")

    if port_busy():
        log("  [2/3] 检测到 %d 端口已在运行，系统可能已启动，直接打开浏览器" % PORT)
        _open_browser("http://127.0.0.1:%d" % PORT)
        log("        若要重启：先关闭标题为「矿地智预服务」的窗口，再运行本脚本。")
        wait_enter()
        return 0

    log("  [2/3] 正在启动后端服务…")
    try:
        subprocess.Popen(
            'start "矿地智预服务" /min cmd /c ""%s" main.py"' % sys.executable,
            cwd=BACKEND, shell=True,
        )
    except Exception as e:
        log("        启动失败：" + str(e))
        wait_enter()
        return 1

    log("  [3/3] 等待服务就绪（最多 60 秒）…")
    for _ in range(60):
        time.sleep(1)
        if port_busy():
            _open_browser("http://127.0.0.1:%d" % PORT)
            log("")
            log("  系统已启动！浏览器已打开 http://127.0.0.1:%d" % PORT)
            log("  默认账号：admin / 123")
            log("  关闭标题为「矿地智预服务」的窗口即可停止系统。")
            wait_enter()
            return 0

    log("")
    log("[错误] 服务 60 秒内没能启动。请查看「启动日志.txt」最后几行：")
    try:
        with io.open(os.path.join(BACKEND, "启动日志.txt"), encoding="utf-8", errors="replace") as f:
            for line in f.read().splitlines()[-12:]:
                log("        " + line[:160])
    except Exception:
        log("        （backend 下没有日志，可能是端口被占用或依赖不完整）")
    log("       仍无法解决时，运行「环境自检.bat」把结果发给开发者。")
    wait_enter()
    return 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        import traceback
        traceback.print_exc()
        wait_enter()
        sys.exit(1)
