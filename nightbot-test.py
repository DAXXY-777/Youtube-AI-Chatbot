from fastapi import FastAPI, Request, HTTPException
from urllib.parse import unquote
import httpx

app = FastAPI()

QWEN_URL = "http://127.0.0.1:8000/v1/chat/completions"
QWEN_MODEL = "qwen"

@app.get("/ai")
async def ai(request: Request, q: str = ""):
    if not q.strip():
        return "Ask me something."

    # Optional: only allow requests from Nightbot
    nightbot_user = request.headers.get("Nightbot-User")
    nightbot_channel = request.headers.get("Nightbot-Channel")

    if not nightbot_user or not nightbot_channel:
        raise HTTPException(status_code=403, detail="Nightbot only")

    payload = {
        "model": QWEN_MODEL,
        "messages": [
            {
                "role": "user",
                "content": q
            }
        ],
        "temperature": 0.7,
        "max_tokens": 100
    }

    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.post(QWEN_URL, json=payload)
        response.raise_for_status()
        data = response.json()

    answer = data["choices"][0]["message"]["content"].strip()

    # Keep the response suitable for Nightbot chat output.
    answer = " ".join(answer.split())
    return answer[:400]




import requests
import webbrowser
from urllib.parse import quote

CLIENT_ID = "YOUR_CLIENT_ID"
CLIENT_SECRET = "YOUR_CLIENT_SECRET"
REDIRECT_URI = "http://localhost:8080"

# 1. Open Nightbot OAuth
auth_url = (
    "https://api.nightbot.tv/oauth2/authorize"
    f"?response_type=code"
    f"&client_id={CLIENT_ID}"
    f"&redirect_uri={quote(REDIRECT_URI)}"
    f"&scope=commands"
)

webbrowser.open(auth_url)

print("Authorize Nightbot.")
code = input("Paste the 'code' from the redirected URL here: ")

# 2. Exchange code for access token
response = requests.post(
    "https://api.nightbot.tv/oauth2/token",
    data={
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "grant_type": "authorization_code",
        "redirect_uri": REDIRECT_URI,
        "code": code,
    },
)

response.raise_for_status()

access_token = response.json()["access_token"]

# 3. Create !hi command
response = requests.post(
    "https://api.nightbot.tv/1/commands",
    headers={
        "Authorization": f"Bearer {access_token}"
    },
    data={
        "name": "!hi",
        "message": "hii nice to meet you",
        "coolDown": 5,
        "userLevel": "everyone",
    },
)

print(response.json())