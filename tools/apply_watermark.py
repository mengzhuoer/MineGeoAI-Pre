# -*- coding: utf-8 -*-
"""矿地智预 MineGeoAI-Pre · 源码水印工具

给项目自有源码文件的头部打上作者水印（by zhuoer mengzhuoda 9.20）。
可重复执行：已带水印的文件会跳过；第三方库（frontend/vendor）不改动。

用法：
    python tools/apply_watermark.py            # 给项目源码打水印（默认在项目根执行）
    python tools/apply_watermark.py --check     # 只检查哪些文件还没打，不修改
"""
import argparse
import os
import sys

WATERMARK = "矿地智预 MineGeoAI-Pre · by zhuoer mengzhuoda · 9.20"
MARK_TAG = "zhuoer mengzhuoda"

# 扩展名 → (注释写法, 说明)；插入位置见 _insert
RULES = {
    ".py": "# ", ".js": "// ", ".css": "/* ", ".html": "<!-- ",
    ".bat": ":: ", ".sh": "# ", ".txt": "# ", ".md": "<!-- ",
}
# 这些目录属第三方或历史产物，不动
SKIP_DIRS = {"vendor", "__pycache__", "node_modules", ".git", ".zcode",
             "exe本体", "参考-旧版Electron源码", "_exe_extract", "发布", "dist", "build"}
SKIP_NAMES = {"vue.global.prod.js", "echarts.min.js", "leaflet.js", "leaflet.css"}


def _mark(ext: str) -> str:
    body = WATERMARK
    if ext == ".css":
        return f"/* {body} */\n"
    if ext == ".html":
        return f"<!-- {body} -->\n"
    if ext == ".md":
        return f"<!-- {body} -->\n"
    return RULES[ext] + body + "\n"


def _insert(path: str, text: str, ext: str) -> str:
    """按文件类型选择插入位置，避免破坏 shebang / 编码声明 / DOCTYPE"""
    lines = text.splitlines(keepends=True)
    at = 0
    if lines:
        first = lines[0]
        # Python 的 coding 声明必须留在前两行
        if ext == ".py" and first.startswith("#") and "coding" in first:
            at = 1
        # HTML 注释必须在 DOCTYPE 之后，否则触发怪异模式
        elif ext == ".html" and first.lstrip().lower().startswith("<!doctype"):
            at = 1
        # bat 的 @echo off 放最前，注释插在其后
        elif ext == ".bat" and first.lstrip().lower().startswith("@echo off"):
            at = 1
    return "".join(lines[:at]) + _mark(ext) + "".join(lines[at:])


def iter_files(root: str):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for fn in filenames:
            ext = os.path.splitext(fn)[1].lower()
            if ext not in RULES or fn in SKIP_NAMES:
                continue
            yield os.path.join(dirpath, fn), ext


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    ap.add_argument("--check", action="store_true", help="只列出未打水印的文件")
    args = ap.parse_args()

    todo, done, skipped = [], 0, 0
    for path, ext in iter_files(args.root):
        try:
            with open(path, encoding="utf-8") as f:
                text = f.read()
        except (UnicodeDecodeError, OSError):
            skipped += 1
            continue
        head = "".join(text.splitlines(keepends=True)[:4])
        if MARK_TAG in head:
            done += 1
            continue
        todo.append(path)
        if not args.check:
            with open(path, "w", encoding="utf-8", newline="") as f:
                f.write(_insert(path, text, ext))

    verb = "待打水印" if args.check else "已打水印"
    for p in todo:
        print(f"  {verb}: {os.path.relpath(p, args.root)}")
    print(f"\n{verb} {len(todo)} 个文件 · 已带水印 {done} 个 · 跳过（非文本）{skipped} 个")
    print(f"水印内容：{WATERMARK}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
