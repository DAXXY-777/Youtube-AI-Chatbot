import requests
import webbrowser
from urllib.parse import quote

CLIENT_ID = "ed1612ef1371e887260a906a4b747376"
CLIENT_SECRET = "3f5c61768d63047acc129290bf2d3a8141bfd55d2c956a360f536f2e2e1e2284"
REDIRECT_URI = "http://localhost:3000"

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