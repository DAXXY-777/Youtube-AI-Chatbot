from fastapi import FastAPI, Request, HTTPException
from base import ChatRequest as chatrequest
from base import URL
from openai import AsyncOpenAI
from urllib.parse import parse_qs
from chatservice import get_video_id, stream_chat
from fastapi.responses import StreamingResponse
import json 

system_prompt = """
You are a helpful, accurate, and thoughtful AI assistant.

Your goals are:
- Answer questions clearly and correctly.
- Ask clarifying questions when needed.
- Explain complex topics in simple language.
- Be honest about uncertainty and avoid making up facts.
- Adapt your tone to the user's preferences.
- Provide step-by-step guidance for technical or complex tasks.
- Prioritize safety, privacy, and user well-being.
- Format responses with headings, bullet points, and examples when helpful.
- If you don't know something, say so and suggest ways to find the answer.
- Avoid unnecessary verbosity while remaining complete.
"""

llama_client = AsyncOpenAI(
    base_url="http://127.0.0.1:8080/v1",
    api_key="local"
)


app=FastAPI()

@app.post("/ai")
async def chat(request: chatrequest):
    stream = await llama_client.chat.completions.create(
        model = "C:\\Users\\devmu\\Desktop\\Projects\\Current-projects\\chat-v1\\backend\\gguf-models\\Qwen3.5-9B-Q4_K_M.gguf",
        messages=[
            {
                "role": "system",
                "content": system_prompt,
            },
            {
                "role": "user",
                "content": request.prompt,
            },
        ],
        stream=False,
    )

    return {
        "response": stream.choices[0].message.content
    }


def create_chat_stream(URL: str):
    try:

        for message in stream_chat(URL):

            event = {
                "type": "chat",
                "data": message,
            }

            # NDJSON:
            # one JSON object per line
            yield json.dumps(
                event,
                ensure_ascii=False,
            ) + "\n"

        # Chat/livestream ended
        yield json.dumps({
            "type": "end"
        }) + "\n"

    except Exception as exc:

        yield json.dumps({
            "type": "error",
            "message": str(exc),
        }) + "\n"


@app.post("/api/chat/stream")
def chat_endpoint(request: URL):

    # Validate before starting the HTTP stream.
    if not get_video_id(request.url):
        raise HTTPException(
            status_code=400,
            detail="Invalid YouTube URL",
        )

    return StreamingResponse(
        create_chat_stream(request.url),
        media_type="application/x-ndjson",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )

@app.get("/command")
async def command(request: Request, message: str = ""):
    user_header = request.headers.get("Nightbot-User", "")

    user_data = parse_qs(user_header)
    username = user_data.get("displayName", ["unknown"])[0]

    print(f"Username: {username}")
    print(f"Message: {message}")

    return f"{username} {message} this is a test and hi"