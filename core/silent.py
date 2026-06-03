"""静默模式：将解析到的媒体文件存储到本地目录，不发送到聊天"""

import asyncio
import json
import re
import shutil
from datetime import datetime
from pathlib import Path

from astrbot.api import logger

from .data import (
    AudioContent,
    DynamicContent,
    FileContent,
    GraphicsContent,
    ImageContent,
    MediaContent,
    ParseResult,
    TextContent,
    VideoContent,
)


# 计数标签映射
_COUNT_LABELS = {
    "video": "视频",
    "image": "图片",
    "audio": "音频",
    "file": "文件",
    "dynamic": "动态图",
    "graphics": "图文",
}


def sanitize_filename(name: str) -> str:
    """去除文件名中的不合法字符"""
    # 去除 Windows/Unix 不合法字符及控制字符
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '', name)
    # 去除首尾空格和点
    name = name.strip(' .')
    # 截断到 200 字符
    if len(name) > 200:
        name = name[:200].rstrip(' .')
    return name or "untitled"


def resolve_unique_path(directory: Path, stem: str, suffix: str) -> Path:
    """生成唯一文件路径，重名时追加时间戳"""
    path = directory / f"{stem}{suffix}"
    if not path.exists():
        return path
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    return directory / f"{stem}_{ts}{suffix}"


def _get_content_type_label(content: MediaContent) -> str:
    """根据内容类型返回计数 key"""
    if isinstance(content, VideoContent):
        return "video"
    if isinstance(content, ImageContent):
        return "image"
    if isinstance(content, AudioContent):
        return "audio"
    if isinstance(content, FileContent):
        return "file"
    if isinstance(content, DynamicContent):
        return "dynamic"
    if isinstance(content, GraphicsContent):
        return "graphics"
    return "file"


async def _collect_all_contents(parse_res: ParseResult) -> list[MediaContent]:
    """收集所有需要存储的媒体内容（包括转发内容），跳过 TextContent"""
    items: list[MediaContent] = []
    for cont in parse_res.contents:
        if not isinstance(cont, TextContent):
            items.append(cont)
    if parse_res.repost:
        for cont in parse_res.repost.contents:
            if not isinstance(cont, TextContent):
                items.append(cont)
    return items


async def store_media(silent_dir: Path, parse_res: ParseResult) -> dict:
    """将解析结果中的媒体文件存储到指定目录，返回结构化记录"""
    title = sanitize_filename(parse_res.title or "untitled")
    items = await _collect_all_contents(parse_res)

    counts: dict[str, int] = {k: 0 for k in _COUNT_LABELS}
    saved_files: list[str] = []

    # 按类型分组计数器，用于生成序号后缀
    type_counters: dict[str, int] = {}

    for cont in items:
        ctype = _get_content_type_label(cont)
        counts[ctype] += 1
        type_counters.setdefault(ctype, 0)
        idx = type_counters[ctype]
        type_counters[ctype] += 1

        try:
            src_path = await cont.get_path()
        except Exception as e:
            logger.warning(f"[静默模式] 获取文件路径失败: {e}")
            continue

        suffix = src_path.suffix

        # 构建文件名：标题 + 类型序号
        if ctype == "video":
            # 视频不带序号（通常只有一个），多个时加序号
            file_stem = title if counts[ctype] == 1 else f"{title}_{counts[ctype]}"
        elif ctype in ("image", "graphics", "dynamic"):
            file_stem = f"{title}_{counts[ctype]}" if counts[ctype] > 1 else title
        else:
            file_stem = title if counts[ctype] == 1 else f"{title}_{counts[ctype]}"

        dest = resolve_unique_path(silent_dir, file_stem, suffix)
        try:
            await asyncio.to_thread(shutil.copy2, src_path, dest)
            saved_files.append(dest.name)
            logger.info(f"[静默模式] 已存储: {dest.name}")
        except Exception as e:
            logger.warning(f"[静默模式] 复制文件失败 {src_path} -> {dest}: {e}")

        # 视频封面也存储
        if isinstance(cont, VideoContent):
            try:
                cover_path = await cont.get_cover_path()
                if cover_path and cover_path.exists():
                    cover_stem = f"{file_stem}_cover"
                    cover_dest = resolve_unique_path(silent_dir, cover_stem, cover_path.suffix)
                    await asyncio.to_thread(shutil.copy2, cover_path, cover_dest)
                    saved_files.append(cover_dest.name)
            except Exception as e:
                logger.warning(f"[静默模式] 存储封面失败: {e}")

    return {
        "title": parse_res.title or "untitled",
        "platform": parse_res.platform.display_name,
        "url": parse_res.url,
        "timestamp": datetime.now().isoformat(),
        "source_timestamp": parse_res.formatted_datetime(),
        "counts": counts,
        "files": saved_files,
    }


async def append_log(silent_dir: Path, record: dict) -> None:
    """追加记录到 silent_log.json"""
    log_path = silent_dir / "silent_log.json"

    def _do():
        data: list[dict] = []
        if log_path.exists():
            try:
                with log_path.open("r", encoding="utf-8") as f:
                    data = json.load(f)
            except (json.JSONDecodeError, OSError):
                data = []
        data.append(record)
        with log_path.open("w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    await asyncio.to_thread(_do)


def build_notification(record: dict, silent_dir: Path) -> str:
    """生成存储确认通知消息"""
    parts: list[str] = []
    for key, label in _COUNT_LABELS.items():
        n = record["counts"].get(key, 0)
        if n > 0:
            parts.append(f"{n}个{label}")

    desc = "、".join(parts) if parts else "无媒体文件"
    return f"已存储「{record['title']}」→ {silent_dir}（{desc}）"
