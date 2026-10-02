from typing import Optional

import httpx

from .config import settings


async def send_text_to_n8n(raw_text: str, image_filename: Optional[str] = None) -> dict:
    payload = {"raw_text": raw_text, "source_file": image_filename}

    async with httpx.AsyncClient(timeout=settings.n8n_timeout_seconds) as client:
        response = await client.post(settings.n8n_webhook_url, json=payload)
        response.raise_for_status()
        return response.json()
