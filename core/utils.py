import hashlib
import json
import os
import tempfile
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Union

import aiohttp

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent
from astrbot.api.message_components import Image, Reply

try:
    from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event import (
        AiocqhttpMessageEvent,
    )

    _AIOCQHTTP_AVAILABLE = True
except ImportError:
    _AIOCQHTTP_AVAILABLE = False
    AiocqhttpMessageEvent = None  # type: ignore[assignment, misc]

BytesOrStr = Union[str, bytes]  # noqa: UP007


def stable_hash(text: str) -> int:
    """Return a stable integer hash (0-2**32-1) that does not vary across
    Python processes (unlike the built-in ``hash()`` which is randomized
    when PYTHONHASHSEED is set).

    Uses the first 8 bytes of md5 to produce a 64-bit value, then masks to
    32 bits for safe modular arithmetic.
    """
    digest = hashlib.md5(text.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "little") & 0xFFFFFFFF


def atomic_write_json(file_path: Path | str, data: Any) -> None:
    """Atomically write JSON data to a file (write-to-temp then rename)."""
    file_path = Path(file_path)
    fd, tmp_path = tempfile.mkstemp(dir=file_path.parent, suffix=".tmp", prefix=".tmp_")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, file_path)
    except Exception:
        # Clean up temp file on failure
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def get_ats(event) -> list[str]:
    """获取被at者们的id列表,(@增强版)"""
    if not _AIOCQHTTP_AVAILABLE:
        logger.debug("[utils] AiocqhttpMessageEvent 不可用，get_ats 返回空列表")
        return []
    from astrbot.api.message_components import At

    ats = [str(seg.qq) for seg in event.get_messages()[1:] if isinstance(seg, At)]
    for arg in event.message_str.split(" "):
        if arg.startswith("@") and arg[1:].isdigit():
            ats.append(arg[1:])
    return ats


async def get_nickname(event, user_id) -> str:
    """获取指定群友的群昵称或Q名"""
    if not _AIOCQHTTP_AVAILABLE:
        return str(user_id)
    client = event.bot
    group_id = event.get_group_id()
    if group_id:
        member_info = await client.get_group_member_info(
            group_id=int(group_id), user_id=int(user_id)
        )
        return member_info.get("card") or member_info.get("nickname")
    else:
        stranger_info = await client.get_stranger_info(user_id=int(user_id))
        return stranger_info.get("nickname")


async def download_file(url: str) -> bytes | None:
    """下载图片或读取本地文件（仅允许http/https URL）"""
    # 安全检查：只允许 http/https 协议
    if not url.startswith(("http://", "https://")):
        logger.warning(f"拒绝非HTTP URL: {url}")
        return None

    try:
        timeout = aiohttp.ClientTimeout(total=30)
        async with aiohttp.ClientSession(timeout=timeout) as client:
            response = await client.get(url)
            if response.status != 200:
                logger.error(f"图片下载失败: HTTP {response.status}, URL: {url}")
                return None
            img_bytes = await response.read()
            return img_bytes
    except Exception as e:
        logger.error(f"图片下载失败: {url}, 错误: {e}")
        return None


async def get_image_urls(event: AstrMessageEvent, reply: bool = True) -> list[str]:
    """获取图片url列表"""
    chain = event.get_messages()
    images: list[str] = []
    # 遍历引用消息
    if reply:
        reply_seg = next((seg for seg in chain if isinstance(seg, Reply)), None)
        if reply_seg and reply_seg.chain:
            for seg in reply_seg.chain:
                if isinstance(seg, Image) and seg.url:
                    images.append(seg.url)
    # 遍历原始消息
    for seg in chain:
        if isinstance(seg, Image) and seg.url:
            images.append(seg.url)
    return images


def get_reply_message_str(event: AstrMessageEvent) -> str | None:
    """
    获取被引用的消息解析后的纯文本消息字符串。
    """
    return next(
        (
            seg.message_str
            for seg in event.message_obj.message
            if isinstance(seg, Reply)
        ),
        None,
    )


async def normalize_images(images: Sequence[BytesOrStr] | None) -> list[bytes]:
    """
    将 str/bytes 混合列表统一转成 bytes 列表：
    - str -> 下载后转 bytes（下载失败则忽略）
    - bytes -> 原样保留
    - None -> 空列表
    """
    if images is None:
        return []

    cleaned: list[bytes] = []
    for item in images:
        if isinstance(item, bytes):
            cleaned.append(item)
        elif isinstance(item, str):
            file = await download_file(item)
            if file is not None:
                cleaned.append(file)
        else:
            raise TypeError(f"image 必须是 str 或 bytes，收到 {type(item)}")
    return cleaned


def rotate_jsonl_if_needed(
    file_path: Path | str,
    max_lines: int,
    force: bool = False,
) -> bool:
    """Rotate a JSONL file by keeping only the most recent half when it exceeds max_lines.

    Args:
        file_path: Path to the JSONL file.
        max_lines: Maximum number of lines before rotation triggers. Use 0 to disable.
        force: If True, always perform rotation check regardless of heuristic.

    Returns:
        True if rotation was performed, False otherwise.
    """
    if max_lines <= 0:
        return False

    file_path = Path(file_path)
    if not file_path.exists():
        return False

    # Count lines first (cheap)
    line_count = 0
    with open(file_path, encoding="utf-8") as f:
        for _ in f:
            line_count += 1

    if line_count <= max_lines:
        return False

    # Read all valid lines, keep the most recent half
    keep_count = max_lines // 2
    lines: list[str] = []
    with open(file_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                json.loads(line)  # validate
                lines.append(line)
            except json.JSONDecodeError:
                continue

    kept = lines[-keep_count:] if keep_count > 0 else []

    # Write back atomically via temp file + os.replace
    import os
    import tempfile

    fd, tmp_path = tempfile.mkstemp(dir=file_path.parent, suffix=".tmp", prefix=".tmp_")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            for line in kept:
                f.write(line + "\n")
        os.replace(tmp_path, file_path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise

    removed = line_count - len(kept)
    logger.info(
        f"[JSONL Rotation] {file_path.name} {line_count} -> {len(kept)} lines "
        f"(removed {removed} old records)"
    )
    return True
