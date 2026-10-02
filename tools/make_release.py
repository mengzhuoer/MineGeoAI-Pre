# -*- coding: utf-8 -*-
# 矿地智预 MineGeoAI-Pre · by zhuoer mengzhuoda · 9.20
"""矿地智预 · 发布打包

把系统打成可分发的版本目录与 zip：
  发布/矿地智预-v<版本>/        ← 可直接运行的目录
  发布/矿地智预-v<版本>.zip     ← 分发用压缩包

包内附独立运行三件套 + 自检：启动系统.bat（自诊断/自动装依赖/镜像回退）、
安装依赖.bat、环境自检.bat、使用说明.txt、VERSION。
排除用户数据与临时产物（数据库、个人文件、报告、密钥、缓存），
保留三个矿区数据集与原始素材，开箱即可演示。

用法：
    python tools/make_release.py                # 版本取 backend/main.py 的 APP_VERSION
    python tools/make_release.py --version 1.1  # 指定版本号
"""
import argparse
import datetime
import os
import re
import shutil
import sys
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AUTHOR = "by zhuoer mengzhuoda · 9.20"

# 不打包：用户数据 / 缓存 / 历史产物 / 第三方参考
EXCLUDE_DIRS = {"__pycache__", ".git", ".zcode", "storage", "reports", "发布",
                "exe本体", "参考-旧版Electron源码", "_exe_extract", "node_modules",
                ".venv", "venv", "dist", "build", "downloads"}   # downloads=官网离线包下载区（1.4GB+，防递归打进发布包）
EXCLUDE_FILES = {"minegeoai.db", "minegeoai.db-shm", "minegeoai.db-wal",
                 "auth_secret.key", "server.log", "启动日志.txt", "_regen.py",
                 "_last_pdf.txt", "auth.db", ".DS_Store"}
EXCLUDE_EXT = {".pyc", ".pyo", ".log", ".tmp"}

# 注意：批处理里【不能出现中文】——cmd 在 GBK 控制台下按字节解析 UTF-8 汉字，
# 汉字的字节会落进 GBK 标点区间（| & > 等），把命令行切碎导致脚本自伤。
# 因此这里只保留 ASCII，所有中文提示与判断都在 tools/boot.py 里（Python 控制台输出正常）。
LAUNCHER = r"""@echo off
chcp 65001 >nul
title MineGeoAI-Pre v{ver}
cd /d "%~dp0"

rem ALWAYS use call before another .bat: without call, cmd transfers control and
rem this script dies silently when the invoked file ends (window flashes and closes).
rem On other PCs "python" may be a wrapper .bat or a Store alias; call is safe for both.
if exist "%~dp0runtime\python\python.exe" goto :bundled
set "PY="
call py -3 -c "import sys;sys.exit(0 if sys.version_info>=(3,10) else 1)" >nul 2>&1
if not errorlevel 1 set "PY=py -3"
if not defined PY (
  call python -c "import sys;sys.exit(0 if sys.version_info>=(3,10) else 1)" >nul 2>&1
  if not errorlevel 1 set "PY=python"
)

if not defined PY goto :nopython
call %PY% "%~dp0tools\boot.py"
goto :eof

:bundled
rem Bundled Python runtime shipped with this package: no external Python needed.
call "%~dp0runtime\python\python.exe" "%~dp0tools\boot.py"
goto :eof

:nopython
echo.
echo  ============================================================
echo   Python 3.10 or newer was not found on this computer.
echo   [Mei you jian ce dao Python 3.10 ji yi shang ban ben]
echo.
echo   1) Install Python 3.10+ from:
echo        https://www.python.org/downloads/
echo      IMPORTANT: check "Add python.exe to PATH" while installing.
echo   2) Reboot this computer, then run this file again.
echo   3) If Python IS installed and you still see this message,
echo      double-click the self-check .bat in this folder and
echo      send its window content to the developer.
echo      (Chinese troubleshooting: see the .txt quick-start file)
echo  ============================================================
echo.
pause
"""

INSTALL_DEPS = r"""@echo off
chcp 65001 >nul
title MineGeoAI-Pre install dependencies
cd /d "%~dp0"
if exist "%~dp0runtime\python\python.exe" goto :bundled
set "PY="
call py -3 -c "import sys;sys.exit(0 if sys.version_info>=(3,10) else 1)" >nul 2>&1
if not errorlevel 1 set "PY=py -3"
if not defined PY (
  call python -c "import sys;sys.exit(0 if sys.version_info>=(3,10) else 1)" >nul 2>&1
  if not errorlevel 1 set "PY=python"
)
if not defined PY goto :nopython
echo Installing runtime dependencies for MineGeoAI-Pre (Python 3.10+)...
call %PY% -m pip install -r requirements.txt
if errorlevel 1 (
  echo.
  echo Official PyPI failed. Retrying with Tsinghua mirror...
  call %PY% -m pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
)
echo.
echo Done. Now double-click the launcher .bat in this folder.
echo (Chinese troubleshooting: see the .txt quick-start file in this folder.)
pause
goto :eof

:nopython
echo.
echo  Python 3.10+ not found. Install from:
echo      https://www.python.org/downloads/
echo  (check "Add python.exe to PATH"), then run this file again.
echo.
pause
"""

SELFCHECK = r"""@echo off
chcp 65001 >nul
title MineGeoAI-Pre self-check
cd /d "%~dp0"
if exist "%~dp0runtime\python\python.exe" goto :bundled
set "PY="
call py -3 -c "import sys;sys.exit(0 if sys.version_info>=(3,10) else 1)" >nul 2>&1
if not errorlevel 1 set "PY=py -3"
if not defined PY (
  call python -c "import sys;sys.exit(0 if sys.version_info>=(3,10) else 1)" >nul 2>&1
  if not errorlevel 1 set "PY=python"
)
if not defined PY goto :nopython
call %PY% "%~dp0tools\selfcheck.py"
goto :eof

:bundled
call "%~dp0runtime\python\python.exe" "%~dp0tools\selfcheck.py"
goto :eof

:nopython
echo.
echo  Python 3.10+ not found, so the self-check cannot run.
echo  [Mei you jian ce dao Python 3.10+]  Install from:
echo      https://www.python.org/downloads/
echo  (check "Add python.exe to PATH"), then run this file again.
echo  Chinese troubleshooting: see the .txt quick-start file in this folder.
echo.
pause
"""

# 环境要求随打包方式而变：内置运行时的包不需要目标电脑装 Python
ENV_REQ_RUNTIME = """    本包已内置 Python 运行时（runtime\\python\\ 约 200+ MB），目标电脑
    【无需安装 Python、无需联网装依赖】，解压后双击「启动系统.bat」即可运行。
    建议整个文件夹放在普通目录（如 D 盘或桌面），不要放 C:\\Program Files。"""
ENV_REQ_SOURCE = """    Python 3.10 及以上（安装第一步请勾选 "Add python.exe to PATH"）
    首次运行会自动安装依赖；也可先双击「安装依赖.bat」"""

# 本地模型是否随包发出，决定这段说明怎么写
MODEL_BUNDLED = """本包【已内置】本地模型 models\\ 下的 GGUF 文件，运行库也随包附带，
      完全离线、开箱即用：打开「图图」→ 右上角「图图设置」→ 点"检测"，
      应显示"本地模型 · 可用"。模型只在本机推理，提问内容不外传。
      【CPU 要求】推理库按多种指令集编译、运行时自动挑最合适的一套：
      新 CPU 全速，老 CPU 自动退到兼容版本（能跑，但慢一些）。
      若提示 0xC000001D「非法指令」，说明这台电脑的 CPU 过老，
      到「图图设置」改用云端 API 方案即可。"""
MODEL_MISSING = """把 GGUF 模型文件放到本目录的 models\\ 下即可（运行库已内置，无需再装东西）。
      文件名建议 qwen2.5-1.5b-instruct-q4_k_m.gguf（找不到就取 models 里最大的那个）。
      模型文件约 1 GB，本压缩包未附带，自行下载后放好，到「图图设置」点"检测"
      即可看到"本地模型 可用"。"""

# 服务器专版（--server）：监听 0.0.0.0、不弹浏览器、预置云端方案
SERVER_LAUNCHER = r"""@echo off
chcp 65001 >nul
title MineGeoAI-Pre v{ver} SERVER
cd /d "%~dp0"

rem ===== SERVER EDITION =====
rem Listen on ALL interfaces so the demo is reachable via the public IP.
rem Also needed: 1) cloud security group allows TCP 8321 inbound
rem              2) Windows firewall rule (run the firewall .bat as admin)
rem Browser auto-open is disabled (KDZY_NO_BROWSER) - servers have no desktop.
set "KDZY_HOST=0.0.0.0"
set "KDZY_NO_BROWSER=1"

if exist "%~dp0runtime\python\python.exe" goto :bundled
set "PY="
call py -3 -c "import sys;sys.exit(0 if sys.version_info>=(3,10) else 1)" >nul 2>&1
if not errorlevel 1 set "PY=py -3"
if not defined PY (
  call python -c "import sys;sys.exit(0 if sys.version_info>=(3,10) else 1)" >nul 2>&1
  if not errorlevel 1 set "PY=python"
)
if not defined PY goto :nopython
call %PY% "%~dp0tools\boot.py"
goto :eof

:bundled
call "%~dp0runtime\python\python.exe" "%~dp0tools\boot.py"
goto :eof

:nopython
echo.
echo  Python 3.10 or newer was not found on this computer.
echo  Use the bundled runtime (runtime\python) or install Python 3.10+.
echo.
pause
"""

SERVER_FW = r"""@echo off
chcp 65001 >nul
title MineGeoAI-Pre open firewall port 8321
netsh advfirewall firewall show rule name="MineGeoAI-Pre 8321" >nul 2>&1
if not errorlevel 1 (
  echo Firewall rule "MineGeoAI-Pre 8321" already exists. Nothing to do.
  pause
  goto :eof
)
netsh advfirewall firewall add rule name="MineGeoAI-Pre 8321" dir=in action=allow protocol=TCP localport=8321
if errorlevel 1 (
  echo.
  echo Failed to add the rule. Right-click this file and choose
  echo "Run as administrator", then run it again. Alternatively open
  echo TCP 8321 inbound in Windows Defender Firewall manually.
) else (
  echo.
  echo Done. TCP 8321 inbound is now allowed by Windows Firewall.
  echo Remember to allow TCP 8321 in the CLOUD security group as well.
)
echo.
pause
"""

# 服务器一键初始化：解压 + 防火墙 + 开机自启 + 立即启动，一次完成。
# 【注意】内容必须纯 ASCII（bat 中文会被 GBK 控制台切碎），中文提示都写在
# 使用说明-服务器版.txt 里；此脚本假设它和 *-server.zip 放在同一目录。
SERVER_INIT = r"""@echo off
chcp 65001 >nul
title MineGeoAI-Pre server one-click init
cd /d "%~dp0"

net session >nul 2>&1
if errorlevel 1 goto :notadmin

set "ZIP="
for %%f in ("%~dp0*-server.zip") do set "ZIP=%%~ff"
if not defined ZIP goto :nozip
if not exist "%ZIP%" goto :nozip

set "DEST=%~dp0kdzy"

if exist "%DEST%\runtime\python\python.exe" goto :already
echo [1/5] Extracting package (about 460 MB) ...
powershell -NoProfile -ExecutionPolicy Bypass -Command "Expand-Archive -LiteralPath '%ZIP%' -DestinationPath '%DEST%' -Force"
if not exist "%DEST%\runtime\python\python.exe" goto :extractfail
:already
echo [2/5] Writing service launcher ...
(
echo @echo off
echo cd /d "%%~dp0backend"
echo set KDZY_HOST=0.0.0.0
echo set KDZY_NO_BROWSER=1
echo "%%~dp0runtime\python\python.exe" main.py
) > "%DEST%kdzy_service.bat"
echo [3/5] Firewall rule ...
netsh advfirewall firewall show rule name="MineGeoAI-Pre 8321" >nul 2>&1
if errorlevel 1 netsh advfirewall firewall add rule name="MineGeoAI-Pre 8321" dir=in action=allow protocol=TCP localport=8321 >nul
echo [4/5] Register auto-start task (run at boot) ...
schtasks /Create /F /TN "MineGeoAI-Pre" /SC ONSTART /RU SYSTEM /TR "\"%DEST%kdzy_service.bat\"" >nul 2>&1
echo [5/5] Starting service ...
schtasks /Run /TN "MineGeoAI-Pre" >nul 2>&1
if errorlevel 1 start "kdzy" /min "%DEST%kdzy_service.bat"
echo.
echo  ==============================================================
echo   INIT DONE.
echo   Check   : http://127.0.0.1:8321   (then http://YOUR_PUBLIC_IP:8321)
echo   Login   : admin / 123  -- CHANGE THIS PASSWORD NOW --
echo             (System Settings - User Management)
echo   Cloud   : allow TCP 8321 inbound in your SECURITY GROUP,
echo             or the site will NOT be reachable from the internet.
echo   AI      : open Ai-Settings page, fill api_base / api_model / api_key.
echo   Files   : %DEST%
echo  ==============================================================
pause
exit /b 0

:notadmin
echo.
echo  [!] RIGHT-CLICK this file and choose "Run as administrator".
echo      (firewall + auto-start task need admin rights)
echo.
pause
exit /b 1

:nozip
echo.
echo  [!] Put this .bat in the SAME folder as *-server.zip, then run again.
echo.
pause
exit /b 1

:extractfail
echo.
echo  [!] Extract failed. Check free disk space, or extract the zip
echo      manually to the "kdzy" folder and run this file again.
echo.
pause
exit /b 1
"""

SERVER_MODEL_TEXT = """服务器专版默认使用【云端 API】方案（已预置）：打开「图图」→「图图设置」，
      选择"云端接口"，填 api_base / api_model / api_key 并保存
      （火山方舟、阿里百炼、DeepSeek 等 OpenAI 兼容接口均可，改 URL 即可）。
      服务器内存有限（2C4G）时不建议跑本地模型；如需离线本地推理，
      把 GGUF 模型放入 models\\ 目录（约 1 GB），再到「图图设置」切回本地方案。"""

SERVER_QUICKSTART = """矿地智预 MineGeoAI-Pre v{ver} · 服务器版使用说明
{author}
================================================================

【本包定位】云服务器（Windows Server 2016/2019/2022，2核4G 及以上）演示专版：
    已去掉 1 GB 本地模型、默认监听 0.0.0.0、预置图图云端 API 方案。
    桌面完整版（含离线模型）请用 矿地智预-v<版本>.zip 常规包。

一、环境要求
{env}

二、五步上线
    1) 解压到普通目录（如 D:\\kdzy，【不要】放 C:\\Program Files）
    2) 右键「开放防火墙端口.bat」→ 以管理员身份运行（放行 Windows 防火墙 8321）
    3) 云控制台 → 安全组 → 添加入方向规则：TCP 8321，源 0.0.0.0/0
    4) 双击「启动系统.bat」启动（本版已自动监听 0.0.0.0，无需再设置）
    5) 本机浏览器访问 http://127.0.0.1:8321 确认服务起来了，
       然后用 http://公网IP:8321 测试外网可达

三、★★ 上线前必做：改掉默认密码 ★★
    公网上的任何人都能打开登录页。首次登录 admin / 123 后，
    立即到「系统设置 → 用户管理」修改 admin 密码，再开始对外演示。

四、图图（AI 助手）配置（本版已预置云端方案）
    「图图」→「图图设置」→ 云端接口，填三项并保存：
        api_base : OpenAI 兼容端点（火山方舟 / 阿里百炼 / DeepSeek 均可）
        api_model: 模型 ID（如 deepseek-v3 / doubao-pro-32k 等，按你的账号来）
        api_key  : 你的 Key
    保存后回对话页提问即可；回答仍会注入当前矿区数据与知识库摘录。
    【口径提醒】走云端会把提问与矿区统计数据发到模型服务商，
    对外演示时请如实说明"演示环境用云端模型，本地部署版可离线、数据不出本机"。

五、常见坑（云服务器专属）
    1) 外网打不开：九成是云【安全组】没放行 8321——防火墙 bat 只管 Windows 这一层
    2) 中文变方块（地图标注/报告）：英文版 Server 镜像缺中文字体，
       把 msyh.ttc、simhei.ttf、simsun.ttc 拷入 C:\\Windows\\Fonts 即可；
       选【中文版】镜像则无此问题
    3) 端口被占用：「启动日志.txt」看最后几行；或改用其他端口：
       在 bat 的 set KDZY_HOST 一行下加  set KDZY_PORT=8322
    4) 服务器重启后服务没了：用「任务计划程序」把 启动系统.bat 设为开机运行，
       或远程桌面里保持会话不注销
    5) 内存吃紧：2C4G 不要开本地模型；任务管理器看 python.exe 占用，
       一般 300-800 MB 属正常
    6) 用 http://公网IP:8321 访问不需要域名备案；一旦绑定域名走 80/443，
       大陆服务器必须完成 ICP 备案

六、自带数据说明
    pingshuo-real  平朔矿区（真实）  CLCD 30m + DEM + 光谱指数，65.15 km²
    pingshuo / anjialing  合成示范数据集
    真实数据集的已知局限见 README「多矿区数据库」一节

七、授权与署名
    本软件由 {author} 开发，源码文件头均带作者水印。
    源码中的第三方库（frontend/vendor）版权归各自作者所有。
"""

QUICKSTART = """矿地智预 MineGeoAI-Pre v{ver} · 使用说明
{author}
================================================================

一、环境要求
{env}

二、启动
    双击「启动系统.bat」，等待浏览器自动打开 http://127.0.0.1:8321
    默认账号：admin / 123（超级管理员，50 GB 存储配额）
    关闭标题为「矿地智预服务」的窗口即可停止系统

★★ 换一台电脑打不开？按这个顺序排查 ★★
    第 0 步：双击「环境自检.bat」，它会报告 Python 版本、缺哪些依赖、
              8321 端口占用、关键文件是否齐全。把窗口内容发我即可定位。
    （下面 ①②③ 是"目标电脑自己装环境"的排查；本包已内置运行时，可跳过不看。）
    ① 提示"没有找到可用的 Python"：那台电脑没装 Python 或安装时没勾 PATH。
       到 https://www.python.org/downloads/ 装 3.10 以上版本，
       安装第一步务必勾选 "Add python.exe to PATH"，装完重启一次再运行。
    ② 装了 Python 仍报错：可能版本太低（3.9 及以下不支持本软件语法），
       或装的是 Microsoft Store 版（命令行会被重定向到应用商店）——
       卸载后改用官网安装包。
    ③ 卡在"正在安装依赖"或安装失败：那台电脑连不上 PyPI（校园网/内网常见）。
       启动脚本会自动改用清华镜像重试；仍失败可用手机热点联网，
       或先在有网的电脑上执行：
           pip download -r requirements.txt -d wheels
       把 wheels 目录一起拷过去，再执行：
           pip install --no-index --find-links=wheels -r requirements.txt
    ④ 卡在"等待服务就绪"然后报错：打开同目录「启动日志.txt」看最后几行。
       最常见原因是 8321 端口被别的程序占用，关掉冲突程序或重启电脑即可。
    ⑤ 窗口一闪就没了：本版本所有出错分支都会停住等你按回车，不会再闪退；
       若仍闪退，按 ① ② 处理。
    ⑥ 浏览器没自动打开：手动打开 http://127.0.0.1:8321（服务其实已在运行）。
    ⑦ 界面能开但功能报错：多半是目录权限问题——不要放在 C:\\Program Files
       这类需要管理员权限的位置，放桌面或 D 盘普通目录即可。
    ⑧ 拷到 U 盘或另一台电脑时，务必整个文件夹一起拷（含 backend、frontend、
       tools、requirements.txt），只拷 .bat 文件跑不起来。
    ⑨ 想完全免安装：见 README「版本与发布」——可另做便携版 exe（体积约 1 GB，
       需在目标系统为 Windows 10/11 64 位时使用）。

三、能做什么
    1. 系统概览 / 数据管理 —— 三个矿区数据库（平朔·真实、平朔、安家岭）实时切换
    2. 数据预处理 —— 辐射定标 → 大气校正 → 去云去噪 → 质量检验；可换用自己的影像
    3. 分类分析 —— 随机森林 / SVM / KNN；也可用导入影像分类（标签取自数据库实测地类）
    4. 变化分析 —— 转移矩阵 · 动态度 · 变化热点；可导入地类图与数据库对比
    5. 预测建模 —— CA-Markov / CLUE-S 多情景推演 + 精度验证（可上传自己的实测地类当真值）
    6. 图像检测 —— 上传/选择自己的 GeoTIFF、影像，做扰动检测、分类、与数据库对比
    7. 报告生成 —— 八类行业标准模板，一键导出 Word / PDF
    8. 文件管理 —— 个人云存储（10 GB），文本可在线编辑（GBK/CRLF 原样写回），图片可在线查看
    9. 图图（AI 助手）—— 桌面毛玻璃浮窗对话：懂矿区业务（数据查询、方法解释、页面跳转），
       也能闲聊；回答里的数字会和数据库实测值逐条核对，对不上会标注"未核实"
   10. 地信遥感知识库 —— 内置 30 节专业知识（波段/指数/分类精度/变化检测/CA-Markov/
       投影与 GeoTIFF/复垦等），助手回答时自动检索引用，可离线运行
   11. 站内消息 —— 与在线用户私聊、接收超级管理员的系统通知；支持**联系人搜索**
       （按账号名、角色或聊天记录内容搜索，↑↓ 选择 Enter 打开）
   12. 界面个性化 —— 4 套主题（清新简约 / 深空大屏 / 极简工作台 / Ubuntu 风）、
       5 种图标风格、3 档图标大小、8 张渐变 + 4 张照片壁纸；个人头像可自定义上传
   13. 土地利用图三种查看 —— 时间轴播放（五期交叉淡入，当年各地类面积同步）、
       两期对比滑块（可拖动分割线 + 只看 A/B/差异叠差）、交互地图（图层开关、
       缩放、比例尺真实准确、单击任意位置查询该点地类与面积）
   14. 手机端网页 —— 同一套后端的移动版（/m/）：概览 / 数据 / 图图 / 功能 / 我的 五个标签，
       覆盖桌面全部 12 个应用；手机可直接调用相机拍照做图像检测

四、手机端怎么用（同一份软件，手机浏览器访问）
    1. 同一台电脑上双击「启动系统.bat」；手机与电脑连同一个 Wi-Fi
    2. 默认只监听本机（127.0.0.1），手机连不上，需要先放开监听：
       关闭正在运行的服务窗口，然后在本目录新建一个 启动系统-手机可访问.bat，内容为：
           @echo off
           chcp 65001 >nul
           cd /d "%~dp0backend"
           set KDZY_HOST=0.0.0.0
           python main.py
       双击它启动（或在本目录执行：set KDZY_HOST=0.0.0.0 后进入 backend 运行 python main.py）
    3. 在电脑上执行 ipconfig 查看内网地址（形如 192.168.1.23）
    4. 手机浏览器打开：http://192.168.1.23:8321/m/   （会自动进入移动版界面）
    5. 移动版覆盖桌面全部功能：概览、数据（地图/明细/对比）、图图、报告、图像检测、
       预处理、分类、变化、预测、文件、图图设置
    ⚠️ 放开监听后，同一局域网内的设备都能打开登录页，请先在桌面版把 admin 的默认密码改掉；
       演示完可以把 KDZY_HOST 去掉，恢复只允许本机访问。

五、图图（AI 助手）怎么用（可选功能，不配也能用其它模块）
    图图有两套推理方案，在「图图设置」里切换，**默认优先本地模型**：
    · 本地模型（推荐，离线、不外传数据）：{model}
    · 云端 API（可选）：填自己的 API Key（兼容 OpenAI 接口的服务均可），
      注意：走云端会把提问内容发到第三方服务器。
    两者都没配时，助手会退化为规则应答（仍能回答数据统计类问题和做页面跳转）。

六、自带数据说明
    pingshuo-real  平朔矿区（真实）  CLCD 30m 土地覆被 + DEM + 光谱指数，65.15 km²
    pingshuo       平朔矿区（示范）  按矿区演化规律合成的演示数据
    anjialing      安家岭矿区（示范）
    真实数据集的已知局限见 README「多矿区数据库」一节

七、授权与署名
    本软件由 {author} 开发，源码文件头均带作者水印。
    源码中的第三方库（frontend/vendor）版权归各自作者所有。
"""


def read_version(path: str) -> str:
    with open(path, encoding="utf-8") as f:
        m = re.search(r'APP_VERSION\s*=\s*"([^"]+)"', f.read())
    return m.group(1) if m else "1.0.0"


def write_text(path: str, text: str):
    """按 UTF-8 + CRLF 写文本（Windows 记事本与 cmd 都要求 CRLF）

    【踩坑】批处理必须是 CRLF 换行：LF-only 的 .bat 里 `goto :label` 会找不到标签，
    cmd 静默退出（返回码 1、无任何输出），表现就是"双击一闪就没"。
    """
    with open(path, "w", encoding="utf-8", newline="\r\n") as f:
        f.write(text)
    if not os.path.isfile(path):
        raise RuntimeError("发布文件写入失败：" + path)


def ignore(dirpath, names):
    return [n for n in names if n in EXCLUDE_DIRS or n in EXCLUDE_FILES
            or os.path.splitext(n)[1].lower() in EXCLUDE_EXT]


def pack_zip(target: str) -> tuple:
    """把发布目录压成 zip，返回 (zip 路径, 文件数, zip 大小MB, 目录大小MB)"""
    out_root = os.path.dirname(target)
    zip_path = target + ".zip"   # 不能用 splitext：版本号里的 .1 会被当扩展名
    if os.path.exists(zip_path):
        os.remove(zip_path)
    n_files = 0
    base = os.path.basename(target)
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for dirpath, dirnames, filenames in os.walk(target):
            dirnames[:] = [d for d in dirnames if d not in EXCLUDE_DIRS]
            for fn in filenames:
                p = os.path.join(dirpath, fn)
                # GGUF 是已量化的权重，deflate 只能省两三个百分点却要多花好几分钟——直接存储
                if fn.lower().endswith(".gguf"):
                    print("  打包本地模型 %s（%.0f MB，不再压缩）…"
                          % (fn, os.path.getsize(p) / 1024 ** 2))
                    z.write(p, os.path.join(base, os.path.relpath(p, target)),
                            compress_type=zipfile.ZIP_STORED)
                else:
                    z.write(p, os.path.join(base, os.path.relpath(p, target)))
                n_files += 1
    size_mb = os.path.getsize(zip_path) / 1024 ** 2
    dir_size = sum(os.path.getsize(os.path.join(dp, f))
                   for dp, _, fs in os.walk(target) for f in fs) / 1024 ** 2
    return zip_path, n_files, size_mb, dir_size


def build(version: str, with_runtime: bool = False, with_model: bool = False,
          server: bool = False) -> str:
    out_root = os.path.join(ROOT, "发布")
    target = os.path.join(out_root, "矿地智预-v" + version)
    if os.path.isdir(target):
        # Windows 上偶尔有句柄没释放（杀毒扫描、刚跑过包内解释器、资源管理器预览），
        # rmtree 会抛 WinError 32；此时先改名让路，别让整次打包白费。
        try:
            shutil.rmtree(target)
        except PermissionError as e:
            aside = target + ".old-" + datetime.datetime.now().strftime("%H%M%S")
            os.rename(target, aside)
            print("！旧发布目录被占用，已改名让路：%s\n  （确认无用后可手动删除；本次报错：%s）"
                  % (os.path.basename(aside), str(e)[:80]))
    os.makedirs(target, exist_ok=True)
    model_text = MODEL_BUNDLED if with_model else MODEL_MISSING

    # 复制项目（排除用户数据与缓存）
    # 服务器专版不带 docs/（PPT 素材、视频、海报等宣传资料共数百 MB，云上用不上）
    items = ("backend", "frontend", "tools", "README.md", "requirements.txt") if server \
        else ("backend", "frontend", "tools", "docs", "README.md", "requirements.txt")
    for item in items:
        src = os.path.join(ROOT, item)
        if not os.path.exists(src):
            continue
        dst = os.path.join(target, item)
        if os.path.isdir(src):
            shutil.copytree(src, dst, ignore=ignore)
        else:
            shutil.copy2(src, dst)

    # 发布用文件：版本 / 启动 / 依赖 / 自检 / 快速上手
    write_text(os.path.join(target, "VERSION"),
               "矿地智预 MineGeoAI-Pre v" + version + "\n"
               + "构建日期 " + datetime.date.today().isoformat() + "\n"
               + AUTHOR + "\n")
    if server:
        # 服务器专版：默认监听 0.0.0.0、不弹浏览器、附防火墙脚本与云部署说明
        write_text(os.path.join(target, "启动系统.bat"), SERVER_LAUNCHER.format(ver=version))
        write_text(os.path.join(target, "开放防火墙端口.bat"), SERVER_FW)
        write_text(os.path.join(target, "使用说明-服务器版.txt"),
                   SERVER_QUICKSTART.format(ver=version, author=AUTHOR,
                                            env=ENV_REQ_RUNTIME if with_runtime else ENV_REQ_SOURCE))
        # 一键初始化脚本不进解压目录，而是放在包根（与 zip 同级的入口）：zip 里也带一份，
        # 用户把它解出来与 zip 一起放服务器任意目录即可双击
        write_text(os.path.join(target, "服务器一键初始化.bat"), SERVER_INIT)
        # 使用说明主文件仍保留（功能清单等通用章节），模型段换服务器口径
        model_text = SERVER_MODEL_TEXT
        write_text(os.path.join(target, "使用说明.txt"),
                   QUICKSTART.format(ver=version, author=AUTHOR, model=model_text,
                                     env=ENV_REQ_RUNTIME if with_runtime else ENV_REQ_SOURCE))
        # 预置云端方案：服务器上默认走 API（Key 留空由用户在「图图设置」填写，
        # 绝不把开发机的 Key 带进发布包）
        import json as _json
        lp = os.path.join(target, "backend", "data", "llm.json")
        try:
            conf = _json.load(open(lp, encoding="utf-8"))
        except Exception:
            conf = {}
        conf["provider"] = "api"
        conf.pop("api_key", None)
        with open(lp, "w", encoding="utf-8") as f:
            f.write(_json.dumps(conf, ensure_ascii=False, indent=2))
        print("  服务器版：llm.json 已预置 provider=api（api_key 置空）")
    else:
        write_text(os.path.join(target, "启动系统.bat"), LAUNCHER.format(ver=version, author=AUTHOR))
        write_text(os.path.join(target, "安装依赖.bat"), INSTALL_DEPS)
        write_text(os.path.join(target, "环境自检.bat"), SELFCHECK)
        write_text(os.path.join(target, "使用说明.txt"),
                   QUICKSTART.format(ver=version, author=AUTHOR, model=model_text,
                                     env=ENV_REQ_RUNTIME if with_runtime else ENV_REQ_SOURCE))

    return target


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--version", default=None)
    ap.add_argument("--with-runtime", action="store_true",
                    help="同时内置 Python 运行时（约 +235 MB，目标电脑无需装 Python）")
    ap.add_argument("--with-model", action="store_true",
                    help="把 models/ 下的 GGUF 本地模型一并打进包（约 +1.1 GB，离线可用 AI 助手）")
    ap.add_argument("--server", action="store_true",
                    help="服务器专版：监听 0.0.0.0、不弹浏览器、预置图图云端方案、附防火墙脚本与云部署说明")
    a = ap.parse_args()
    ver = a.version or read_version(os.path.join(ROOT, "backend", "main.py"))
    target = build(ver, with_runtime=a.with_runtime, with_model=a.with_model,
                   server=a.server)
    if a.with_model:
        src_models = os.path.join(ROOT, "models")
        guffs = ([f for f in os.listdir(src_models) if f.lower().endswith(".gguf")]
                 if os.path.isdir(src_models) else [])
        if not guffs:
            print("！--with-model：models/ 下没有 .gguf 文件，跳过")
        else:
            dst_models = os.path.join(target, "models")
            os.makedirs(dst_models, exist_ok=True)
            for fn in guffs:
                print("正在打包本地模型 %s（约 1 GB，需要一点时间）…" % fn)
                shutil.copy2(os.path.join(src_models, fn), os.path.join(dst_models, fn))
    if a.with_runtime:
        print("正在集成内置 Python 运行时（约 235 MB，含本地模型推理库）…")
        import subprocess as _sp
        _sp.run([sys.executable, os.path.join(ROOT, "tools", "bundle_python.py"),
                 "--target", target], check=False)
    # 只在全部内容就位后压一次包（此前先压一遍再压一遍会白跑几分钟）
    zip_path, n, zip_mb, dir_mb = pack_zip(target)
    print("版本      : v%s  (%s)" % (ver, AUTHOR))
    print("发布目录  : %s  (%.1f MB)" % (target, dir_mb))
    print("压缩包    : %s  (%.1f MB, %d 个文件)" % (zip_path, zip_mb, n))
    sys.exit(0)
