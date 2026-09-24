"""Minimize outbound text; conservative contact/identifier detection, not anonymity proof."""

import re

from .canonical import BodyBlock

_CONTACT = re.compile(
    r"(?i)https?://|www\.|[\w.+-]+@[\w.-]+\.[a-z]{2,}|"
    r"(?<!\d)(?:\+?86[ -]?)?1[3-9](?:[ -]?\d){9}(?!\d)|"
    r"(?<!\d)\d{17}[\dX](?!\w)|"
    r"手机号|身份证|微信|微[信号]|联系方式|联系电话|家庭住址|我家地址|邮箱|"
    r"\b(?:wechat|vx|qq)\s*[:：号=]|\b(?:cookie|authorization|session_secret)\b"
)


def outbound_blocks(blocks: tuple[BodyBlock, ...], *, max_chars: int = 6000) -> tuple[BodyBlock, ...]:
    """Omit whole blocks to retain original offsets. Never substitute redacted quotes."""
    selected = []
    used = 0
    for block in blocks[:120]:
        if _CONTACT.search(block.text):
            continue
        if used + len(block.normalized_text) > max_chars:
            break
        selected.append(block)
        used += len(block.normalized_text)
    return tuple(selected)
