from __future__ import annotations

import base64
import time
from pathlib import Path

from openai import AsyncOpenAI

IMAGE_PROMPT_TEMPLATE = """\
Editorial illustration for a Telegram post about Uzbek tax/accounting/finance news.
Topic: {title}
Style: clean, modern, flat-design news illustration, no text, no letters, no logos."""


class ImageAI:
    def __init__(self, api_key: str, model: str, size: str, output_dir: Path):
        self._client = AsyncOpenAI(api_key=api_key)
        self._model = model
        self._size = size
        self._output_dir = output_dir
        self._output_dir.mkdir(parents=True, exist_ok=True)

    async def generate(self, title: str) -> Path:
        prompt = IMAGE_PROMPT_TEMPLATE.format(title=title[:300])
        result = await self._client.images.generate(
            model=self._model,
            prompt=prompt,
            size=self._size,
            n=1,
        )
        b64_data = result.data[0].b64_json
        if not b64_data:
            raise RuntimeError("Image API returned no image data")

        image_bytes = base64.b64decode(b64_data)
        out_path = self._output_dir / f"post_{int(time.time() * 1000)}.png"
        out_path.write_bytes(image_bytes)
        return out_path
