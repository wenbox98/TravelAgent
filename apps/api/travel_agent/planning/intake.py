"""Extract an explicitly named region, without choosing a city or an itinerary."""

import re


def destination_from_idea(text: str) -> str:
    text = text.strip()
    match = re.search(r"(?:去|到)([^，。！？；,\n\d]{1,40})", text)
    region = match[1] if match else re.split(r"[，。！？；,\n\d]", text, maxsplit=1)[0]
    region = re.split(r"[一二两三四五六七八九十]+(?:天|日)", region, maxsplit=1)[0]
    region = re.sub(r"(?:游玩|旅游|旅行|玩|逛|待|住)(?:一下|一趟)?$", "", region).strip()
    if (
        not region
        or len(region) > 30
        or re.search(r"想|希望|预算|安排|轻松|随便|哪里|哪儿|或者|还是|或|然后", region)
    ):
        raise ValueError("DESTINATION_REQUIRED")
    return region
