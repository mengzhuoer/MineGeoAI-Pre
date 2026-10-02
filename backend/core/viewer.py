# -*- coding: utf-8 -*-
# 矿地智预 MineGeoAI-Pre · by zhuoer mengzhuoda · 9.20
"""在线查看支持：判定文件能否在浏览器里直接打开（txt 文本 / jpg 图片等）。

- 判定以扩展名为准、上传时记录的 MIME 兜底：浏览器的 content-type 常常缺失
  （.csv 被标成 application/octet-stream），按它判断会误判。
- tif/tiff 等浏览器无法直接渲染的栅格格式不列入可预览图片，避免"打不开的空窗"。
- 中文文本文件在 Windows 上多为 GBK/ANSI 编码，按 UTF-8 硬解会整篇乱码，
  这里依次尝试 BOM → UTF-8 → GB18030（兼容 GBK/GB2312）→ Big5。
"""
import hashlib
import os

# 保存时的编码白名单：展示名 → (Python 编解码器, BOM 前缀)
# 与 decode_text 返回的 encoding_code 使用同一套取值
CODECS = {
    "utf-8": ("utf-8", b""),
    "utf-8-bom": ("utf-8", b"\xef\xbb\xbf"),
    "utf-16": ("utf-16", b""),          # Python 的 utf-16 编解码器自带 BOM
    "gb18030": ("gb18030", b""),
    "big5": ("big5", b""),
}
CODEC_LABEL = {
    "utf-8": "UTF-8", "utf-8-bom": "UTF-8 (BOM)", "utf-16": "UTF-16",
    "gb18030": "GB18030", "big5": "Big5",
}

# 浏览器 <img> 可直接渲染的图片格式
IMAGE_EXT = {"jpg", "jpeg", "jpe", "jfif", "png", "gif", "webp", "bmp", "svg", "ico", "avif"}

# 可当纯文本查看的扩展名（含 GIS 常见的 .prj 投影定义、.cpg 编码说明）
TEXT_EXT = {
    "txt", "text", "log", "csv", "tsv", "md", "markdown", "json", "xml", "yml", "yaml",
    "ini", "conf", "cfg", "properties", "env", "bat", "cmd", "sh", "ps1", "py", "js",
    "mjs", "ts", "css", "html", "htm", "sql", "java", "c", "cpp", "h", "hpp", "cs",
    "go", "rs", "php", "rb", "r", "tex", "prj", "cpg", "wkt", "gml", "kml",
}

# 预览响应的 Content-Type（不做预览的类型沿用上传时记录的 MIME）
MEDIA = {
    "jpg": "image/jpeg", "jpeg": "image/jpeg", "jpe": "image/jpeg", "jfif": "image/jpeg",
    "png": "image/png", "gif": "image/gif", "webp": "image/webp", "bmp": "image/bmp",
    "svg": "image/svg+xml", "ico": "image/x-icon", "avif": "image/avif",
    "pdf": "application/pdf",
}

# 文本预览最多读取的字节数：超大日志截断展示，避免一次塞满浏览器
TEXT_LIMIT = 2 * 1024 * 1024
# 二进制探测字节数
SNIFF_BYTES = 8192


def ext_of(name: str) -> str:
    return os.path.splitext(name or "")[1].lstrip(".").lower()


def kind_of(name: str) -> str:
    """在线查看类型：image（图片）/ text（文本）/ other（仅可下载）"""
    e = ext_of(name)
    if e in IMAGE_EXT:
        return "image"
    if e in TEXT_EXT:
        return "text"
    return "other"


def media_type(name: str, fallback: str = "") -> str:
    return MEDIA.get(ext_of(name), fallback or "application/octet-stream")


def _decoded(text: str, encoding: str, code: str, strict: bool = True) -> dict:
    return {"text": text, "encoding": encoding, "encoding_code": code, "strict": strict}


def decode_text(raw: bytes) -> dict:
    """探测编码并解码。

    返回 {text, encoding（展示名）, encoding_code（保存用编码）, strict}。
    strict=False 表示只能"替换解码"，此时文本里有无法还原的字节，
    若允许保存会把原文件写坏，因此调用方应禁用编辑。
    """
    if raw.startswith(b"\xef\xbb\xbf"):
        try:
            return _decoded(raw.decode("utf-8-sig"), "UTF-8 (BOM)", "utf-8-bom")
        except UnicodeDecodeError:
            pass
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        try:
            return _decoded(raw.decode("utf-16"), "UTF-16", "utf-16")
        except UnicodeDecodeError:
            pass
    for codec, label in (("utf-8", "UTF-8"), ("gb18030", "GB18030"), ("big5", "Big5")):
        try:
            return _decoded(raw.decode(codec), label, codec)
        except UnicodeDecodeError:
            continue
    # 均无法严格解码：按最可能的中文编码替换解码，至少保证内容可读（仅查看）
    return _decoded(raw.decode("gb18030", "replace"), "GB18030（含无法识别字符）", "", strict=False)


def decode_with(raw: bytes, code: str) -> str:
    """按指定编码严格解码（用户手动指定时使用）；无法解码抛 UnicodeDecodeError。"""
    if code == "utf-8-bom":
        return raw.decode("utf-8-sig")
    if code == "utf-16":
        return raw.decode("utf-16")
    return raw.decode(CODECS[code][0])


def encode_text(text: str, code: str):
    """按指定编码编码文本，返回 bytes；字符无法表示时抛 UnicodeEncodeError。"""
    codec, bom = CODECS.get(code, CODECS["utf-8"])
    if codec == "utf-16":
        return text.encode(codec)          # 自带 BOM
    return bom + text.encode(codec)


def read_text(path: str, name: str, size: int, force_code: str = "") -> dict:
    """读取文本文件用于在线预览/编辑：返回编码、是否截断、正文与内容指纹。

    force_code 非空时按用户指定的编码解码（GB18030 与 Big5 字节区间重叠，
    自动探测可能误判，此时由用户手动指定）。
    """
    with open(path, "rb") as f:
        head = f.read(SNIFF_BYTES)
        # 含 NUL 字节视为二进制（UTF-16 除外，它靠 BOM 识别）
        if b"\x00" in head and not head.startswith((b"\xff\xfe", b"\xfe\xff")):
            return {"name": name, "size": size, "kind": "binary", "text": "", "lines": 0,
                    "editable": False, "sha256": ""}
        rest = f.read(max(0, TEXT_LIMIT - len(head)))
        truncated = f.read(1) != b""
    raw = head + rest
    if force_code:
        if force_code not in CODECS:
            raise ValueError("不支持的编码")
        d = _decoded(decode_with(raw, force_code), CODEC_LABEL[force_code], force_code)
    else:
        d = decode_text(raw)
    return {
        "name": name,
        "size": size,
        "kind": "text",
        "text": d["text"],
        "encoding": d["encoding"],
        "encoding_code": d["encoding_code"],
        "truncated": truncated,
        "lines": d["text"].count("\n") + 1 if d["text"] else 0,
        # 仅当完整读取且编码严格可还原时才允许编辑，避免写坏原文件
        "editable": (not truncated) and d["strict"],
        "sha256": hashlib.sha256(raw).hexdigest(),
    }
