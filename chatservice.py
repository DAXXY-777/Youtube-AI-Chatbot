from collections.abc import Iterator
from urllib.parse import urlparse, parse_qs

import pytchat


def get_video_id(url: str) -> str:
    url = url.strip()

    parsed = urlparse(url)

    # https://youtu.be/VIDEO_ID
    if "youtu.be" in parsed.netloc:
        return parsed.path.strip("/")

    # https://youtube.com/live/VIDEO_ID
    if "/live/" in parsed.path:
        return parsed.path.split("/live/")[1].split("/")[0]

    # https://youtube.com/watch?v=VIDEO_ID
    return parse_qs(parsed.query).get("v", [""])[0]


def stream_chat(url: str) -> Iterator[dict]:
    video_id = get_video_id(url)

    if not video_id:
        raise ValueError("Invalid YouTube URL")

    chat = pytchat.create(
        video_id=video_id,
        interruptable=False,
    )

    try:
        while chat.is_alive():

            for message in chat.get().sync_items():

                yield {
                    "author": message.author.name,
                    "message": message.message,
                    "datetime": message.datetime,
                }

    finally:
        # Clean up the pytchat instance if terminate() exists.
        terminate = getattr(chat, "terminate", None)

        if callable(terminate):
            terminate()