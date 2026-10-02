# -*- coding: utf-8 -*-
"""服务器专版 zip 内容校验"""
import zipfile

z = zipfile.ZipFile(r"D:\Zcode\KDZY\矿地智预-系统\发布\矿地智预-v1.2.0-server.zip")
raw = z.namelist()
names = []
for n in raw:
    try:
        names.append(n.encode("cp437").decode("gbk"))
    except Exception:
        names.append(n)

checks = {
    "启动系统.bat": any(n.endswith("启动系统.bat") for n in names),
    "开放防火墙端口.bat": any(n.endswith("开放防火墙端口.bat") for n in names),
    "使用说明-服务器版.txt": any(n.endswith("使用说明-服务器版.txt") for n in names),
    "runtime/python.exe": any("runtime/python/python.exe" in n for n in names),
    "无 models/": not any("/models/" in n for n in names),
    "无 docs/": not any("/docs/" in n for n in names),
    "backend/data/llm.json": any(n.endswith("backend/data/llm.json") for n in names),
}
for k, v in checks.items():
    print(("✓" if v else "✗"), k)

for n in raw:
    fn = names[raw.index(n)]
    if fn.endswith("llm.json"):
        print("llm.json 内容:", z.read(n).decode("utf-8")[:150].replace("\n", " "))
    if fn.endswith("启动系统.bat"):
        txt = z.read(n).decode("utf-8", "replace")
        print("bat: KDZY_HOST=0.0.0.0 ->", "KDZY_HOST=0.0.0.0" in txt,
              "| KDZY_NO_BROWSER ->", "KDZY_NO_BROWSER" in txt,
              "| 纯ASCII(除chcp注释外无中文) ->", all(ord(c) < 128 for c in txt))
