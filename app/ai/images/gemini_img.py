"""Google rasm generatsiyasi: Imagen (`generate_images`) yoki Gemini image modellari."""

from __future__ import annotations

from typing import Any

from app.ai.types import aspect_ratio


class GeminiImageClient:
    provider = "gemini"

    def __init__(self, api_key: str, model: str, *, http_client: Any = None) -> None:
        from google import genai
        from google.genai import types

        self.model = model
        opts: dict[str, Any] = {}
        if http_client is not None:
            opts["httpx_async_client"] = http_client
        self._client = genai.Client(api_key=api_key, http_options=types.HttpOptions(**opts) if opts else None)

    async def generate(self, prompt: str, *, size: str = "1024x1024") -> bytes:
        from google.genai import types

        ratio = aspect_ratio(size)
        if self.model.startswith("imagen"):
            resp = await self._client.aio.models.generate_images(
                model=self.model,
                prompt=prompt,
                config=types.GenerateImagesConfig(number_of_images=1, aspect_ratio=ratio),
            )
            images = resp.generated_images or []
            if not images or images[0].image is None or not images[0].image.image_bytes:
                raise RuntimeError("Imagen rasm qaytarmadi")
            return images[0].image.image_bytes
        resp2 = await self._client.aio.models.generate_content(
            model=self.model,
            contents=f"{prompt}\nAspect ratio: {ratio}.",
            config=types.GenerateContentConfig(response_modalities=["IMAGE"]),
        )
        for cand in resp2.candidates or []:
            for part in (cand.content.parts if cand.content else None) or []:
                if part.inline_data is not None and part.inline_data.data:
                    return part.inline_data.data
        raise RuntimeError("Gemini javobida rasm yo'q")
