import json
import os

import httpx


API_URL = os.getenv(
    "CHAT_API_URL",
    "http://127.0.0.1:8000",
)


def stream_chat(url: str):

    timeout = httpx.Timeout(
        10.0,
        read=None,
    )

    with httpx.stream(
        method="POST",
        url=f"{API_URL}/api/chat/stream",
        json={
            "url": url,
        },
        timeout=timeout,
    ) as response:

        response.raise_for_status()

        for line in response.iter_lines():

            if not line:
                continue

            yield json.loads(line)