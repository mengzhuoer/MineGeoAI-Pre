# -*- coding: utf-8 -*-
# 矿地智预 MineGeoAI-Pre · by zhuoer mengzhuoda · 9.20
"""矿地智预 · 环境自检（由 环境自检.bat 调用）

为什么放在 Python 里：批处理中的中文在 GBK 控制台下会被 cmd 按字节解析，
UTF-8 汉字的字节可能落在 GBK 标点区间（| & > 等）而把命令行切碎。
Python 写控制台走 Windows UTF-16 接口，中文稳定正常。

排查换电脑打不开时，把本脚本的输出发给开发者即可定位。
"""
import importlib.util
import os
import socket
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKEND = os.path.join(ROOT, "backend")
DEPS = ["fastapi", "uvicorn", "numpy", "scipy", "rasterio", "sklearn",
        "docx", "matplotlib", "PIL", "psutil"]
FILES = ["backend/main.py", "frontend/index.html", "requirements.txt",
         "启动系统.bat", "tools/boot.py"]


def line(t="", *a):
    print(t % a if a else t)


def main():
    line("=" * 56)
    line("  矿地智预 MineGeoAI-Pre · 环境自检")
    line("  by zhuoer mengzhuoda · 9.20")
    line("  把本窗口内容截图发给开发者即可定位问题")
    line("=" * 56)
    line("  自检时间：%s", time.strftime("%Y-%m-%d %H:%M:%S"))
    line("  所在目录：%s", ROOT)

    line("\n[1] Python 解释器（需要 3.10 及以上）")
    v = sys.version_info
    line("  版本：%s.%s.%s  (%s)", v.major, v.minor, v.micro, sys.version.split()[0])
    line("  满足要求(>=3.10)：%s", "是" if v >= (3, 10) else "否 —— 需要升级 Python")
    line("  解释器：%s", sys.executable)
    line("  来源：%s", "内置运行时（随软件打包，无需外部环境）"
         if os.sep + "runtime" + os.sep in os.path.abspath(sys.executable)
         else "系统安装的 Python")
    line("  是否为 Microsoft Store 版：%s",
         "可能是" if "WindowsApps" in sys.executable else "不是")

    line("\n[2] 运行依赖")
    miss = [m for m in DEPS if importlib.util.find_spec(m) is None]
    if miss:
        line("  缺失：%s", ", ".join(miss))
        line("  解决：双击「安装依赖.bat」，或用手机热点联网后重新双击「启动系统.bat」")
    else:
        line("  全部就绪（%d 项）", len(DEPS))

    line("\n[3] 8321 端口占用")
    with socket.socket() as s:
        s.settimeout(0.6)
        using = s.connect_ex(("127.0.0.1", 8321)) == 0
    line("  状态：%s", "已被占用（系统可能已在运行）" if using else "空闲，可以启动")
    if using:
        line("  提示：若打不开界面，先关闭标题为「矿地智预服务」的窗口再重启本脚本")

    line("\n[4] 关键文件")
    for f in FILES:
        line("  %s %s", "OK  " if os.path.isfile(os.path.join(ROOT, f)) else "缺失", f)
    line("  说明：以上缺失通常是把 .bat 单独拷出来运行了——请整个文件夹一起拷")

    line("\n[5] 数据目录")
    db = os.path.join(BACKEND, "data", "minegeoai.db")
    line("  数据库：%s", "已存在" if os.path.isfile(db) else "尚无（首次启动时自动创建）")
    for ds in ("pingshuo-real", "pingshuo", "anjialing"):
        p = os.path.join(BACKEND, "data", ds, "metadata.json")
        line("  数据集 %-14s %s", ds, "就绪" if os.path.isfile(p) else "缺失")

    line("\n[6] 写入权限")
    probe = os.path.join(ROOT, "_write_test.tmp")
    try:
        with open(probe, "w", encoding="utf-8") as f:
            f.write("ok")
        os.remove(probe)
        line("  可写入：是")
    except Exception as e:
        line("  可写入：否 —— %s", e)
        line("  原因多为放在 C:\\Program Files 等需要管理员权限的目录；移到桌面或 D 盘即可")

    line("\n" + "=" * 56)
    try:
        input("按回车键关闭本窗口…")
    except (EOFError, KeyboardInterrupt):
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
