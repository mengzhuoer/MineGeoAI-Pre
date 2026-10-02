# -*- coding: utf-8 -*-
# 矿地智预 MineGeoAI-Pre · by zhuoer mengzhuoda · 9.20
"""打 Linux 部署包：源码 + 一键部署脚本 → 发布/矿地智预-v<版本>-linux.tar.gz

用法：python tools/make_linux_release.py [--version 1.2.0]
产物：发布/矿地智预-v<版本>-linux.tar.gz（约 36 MB）
目标：Ubuntu 22.04+ 服务器；解压后 sudo bash 一键部署.sh 即完成
     （venv + 依赖 + systemd 开机自启，监听 0.0.0.0:8321）
"""
import argparse
import datetime
import os
import re
import shutil
import tarfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AUTHOR = "by zhuoer mengzhuoda · 9.20"
EXCLUDE_DIRS = {"__pycache__", ".git", "storage", "reports", "发布", "runtime",
                "downloads", "docs", "node_modules", ".venv", "venv", "welcome"}
EXCLUDE_FILES = {"minegeoai.db", "minegeoai.db-shm", "minegeoai.db-wal",
                 "auth_secret.key", "server.log", "auth.db", "llm.json"}
EXCLUDE_EXT = {".pyc", ".pyo", ".log", ".tmp", ".bat"}

DEPLOY_SH = """#!/usr/bin/env bash
# 矿地智预 MineGeoAI-Pre Linux 一键部署 · {author}
# 适用：Ubuntu 22.04+（Debian 12 亦可）；请用 root 运行：sudo bash 一键部署.sh
set -e
cd "$(dirname "$0")"

echo "[1/5] 安装系统依赖 python3-venv ..."
apt-get install -y python3-venv >/dev/null 2>&1 || sudo apt-get install -y python3-venv

echo "[2/5] 创建虚拟环境 ..."
[ -d venv ] || python3 -m venv venv

echo "[3/5] 安装 Python 依赖（阿里云镜像，约 1-3 分钟）..."
./venv/bin/pip install -q --upgrade pip -i https://mirrors.aliyun.com/pypi/simple/
./venv/bin/pip install -q -r requirements.txt -i https://mirrors.aliyun.com/pypi/simple/

echo "[4/5] 注册 systemd 服务（开机自启 · 监听 0.0.0.0:8321）..."
cat > /etc/systemd/system/kdzy.service <<UNIT
[Unit]
Description=MineGeoAI-Pre (kdzy) web service
After=network.target

[Service]
Type=simple
WorkingDirectory=$(pwd)/backend
Environment=KDZY_HOST=0.0.0.0
Environment=KDZY_NO_BROWSER=1
ExecStart=$(pwd)/venv/bin/python main.py
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload
systemctl enable --now kdzy

echo "[5/5] 完成！"
echo "  访问    : http://本机IP:8321   （本机可先 curl http://127.0.0.1:8321 验证）"
echo "  登录    : admin / 123 —— 请立即在「系统设置 → 用户管理」修改默认密码"
echo "  云服务器: 请在安全组放行 TCP 8321"
echo "  运维    : systemctl status/restart kdzy · 日志 journalctl -u kdzy -n 50"
echo "  AI 助手 : 默认云端 API 方案，到「图图设置」填 api_base / api_model / api_key"
"""


def read_version(path):
    with open(path, encoding="utf-8") as f:
        m = re.search(r'APP_VERSION\s*=\s*"([^"]+)"', f.read())
    return m.group(1) if m else "1.2.0"


def ignore(_dir, names):
    return [n for n in names if n in EXCLUDE_DIRS or n in EXCLUDE_FILES
            or os.path.splitext(n)[1].lower() in EXCLUDE_EXT]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--version", default=None)
    a = ap.parse_args()
    ver = a.version or read_version(os.path.join(ROOT, "backend", "main.py"))
    top = "矿地智预-v%s-linux" % ver
    out = os.path.join(ROOT, "发布", top + ".tar.gz")
    if os.path.exists(out):
        os.remove(out)

    stage = os.path.join(ROOT, "发布", "_linux_stage", top)
    shutil.rmtree(os.path.dirname(stage), ignore_errors=True)
    os.makedirs(stage, exist_ok=True)
    for item in ("backend", "frontend", "tools", "README.md", "requirements.txt"):
        src = os.path.join(ROOT, item)
        if not os.path.exists(src):
            continue
        dst = os.path.join(stage, item)
        if os.path.isdir(src):
            shutil.copytree(src, dst, ignore=ignore)
        else:
            shutil.copy2(src, dst)
    with open(os.path.join(stage, "一键部署.sh"), "w", encoding="utf-8", newline="\n") as f:
        f.write(DEPLOY_SH.format(author=AUTHOR))
    with open(os.path.join(stage, "VERSION"), "w", encoding="utf-8", newline="\n") as f:
        f.write("矿地智预 MineGeoAI-Pre v%s linux\n构建日期 %s\n%s\n"
                % (ver, datetime.date.today().isoformat(), AUTHOR))

    with tarfile.open(out, "w:gz") as t:
        t.add(stage, arcname=top)
    shutil.rmtree(os.path.dirname(stage), ignore_errors=True)
    print("Linux 包: %s  (%.1f MB)" % (out, os.path.getsize(out) / 1024 ** 2))
    print("解压后用法: tar -xzf *.tar.gz && cd 矿地智预-v%s-linux && sudo bash 一键部署.sh" % ver)


if __name__ == "__main__":
    main()
