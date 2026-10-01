# YT Livestream Chatbot

YT Livestream Chatbot is a Windows-first desktop application for answering
Nightbot `!AI` commands with either a downloaded local GGUF model or an
OpenAI-compatible Cloud provider. It is not hosted by this project: the program
runs on the streamer's computer and opens its private Gradio UI in a Windows
WebView.

## What Runs Where

```text
Desktop window
  -> private Gradio UI at http://127.0.0.1:7860
  -> shared application service and SQLite database
  -> narrow Nightbot API at http://127.0.0.1:7861/api/nightbot/ai
  -> optional user-managed tunnel, VPN, reverse proxy, or VPS endpoint
  -> Nightbot URLFetch
```

`127.0.0.1` means "this computer only." The UI and settings stay on port
`7860`; only the narrow Nightbot API exists on port `7861`. A user who wants a
public endpoint points their own networking solution at `7861`, never at the
private UI.

## The Stack, In Plain English

- **Gradio** draws the configuration screen and message feed.
- **FastAPI** receives the small HTTP request Nightbot makes for `!AI`.
- **Uvicorn** runs those FastAPI applications on local ports.
- **pywebview** displays the local Gradio page in a Windows window.
- **SQLite + SQLAlchemy** keep local configuration and message history in a file.
- **Keyring** stores Cloud API keys in Windows Credential Manager, outside SQLite.
- **llama-cpp-python** runs downloaded GGUF models with Vulkan when available.
- **Hugging Face Hub** downloads only the exact curated GGUF selected by a user.
- **pytchat-ng** listens to the selected public YouTube live chat for transient
  ambient context; it needs no YouTube API key. [pytchat-ng documentation](https://pypi.org/project/pytchat-ng/)

Read [docs/application-guide.md](docs/application-guide.md) for a beginner code
tour covering the request flow and every important function/module.
Read [docs/interview-cheatsheet.md](docs/interview-cheatsheet.md) for an
interview-ready architecture summary, question bank, debugging checklist, and
future-development recipes.

## Run From Source

Install [uv](https://docs.astral.sh/uv/) and Python 3.14 or later:

```powershell
uv sync --group build
uv run python main.py
```

Terminal mode starts both local services and prints their URLs. Stop it with
`Ctrl+C`. To open the desktop window while developing:

```powershell
uv run python desktop.py
```

Windows needs Microsoft Edge WebView2 Runtime for the packaged desktop window.
Modern Windows installations normally include it. [pywebview Windows renderer
guide](https://pywebview.flowrl.com/3.7/guide/renderer)

## Use The App

1. Select **Local** or **Cloud**. Every later `!AI` request uses that global mode.
2. In Local mode, select Qwen or Gemma and choose `Download model`; the GGUF is
   downloaded only then. Downloading and loading happen in the background. The
   previous model remains usable during a download; the app keeps only one model
   in RAM and restores the previous one if a replacement cannot load.
3. In Cloud mode, save the provider URL, key, and model ID. The key goes to
   Credential Manager, not SQLite. An empty key field preserves the existing
   key. Invalid edits do not replace the last working Cloud configuration.
4. Optionally set the current public YouTube live URL. It must be exactly
   `https://www.youtube.com/watch?v=<video-id>`. The app groups Nightbot
   activity under it and keeps the latest 85 ordinary viewer messages in RAM as
   ambient context for the next `!AI` reply. The newest messages are included
   up to the Local model's prompt budget. `!AI` commands are excluded from that
   buffer and it clears on a stream switch or app restart. The listener retries
   every 30 seconds after YouTube chat ends or fails. If YouTube chat cannot be
   read, the current viewer query still receives a normal response.
5. `Test AI` uses the active responder and current ambient context without
   recording a fake chat message or consuming a viewer cooldown.

Each viewer gets one accepted `!AI` request every minute, shared by
Local and Cloud mode and retained across restarts. A blank command replies
`Ask me a question.` The bot asks the model for at most 75 tokens and clips its
plain-text reply to 280 characters, leaving room below YouTube live chat's
300-character limit.

All persistent files stay inside the installer-selected folder:

```text
YT Livestream Chatbot/
  YT Livestream Chatbot.exe
  data/yt-livestream-chatbot.sqlite3
  models/
  logs/yt-livestream-chatbot.log
```

The installer defaults to `Documents\YT Livestream Chatbot`, a writable folder.
Do not choose `Program Files` unless the app has explicit write permission.

## Connect Nightbot

Make only local port `7861` reachable through an endpoint you control. For a
quick Cloudflare prototype, use your own `cloudflared` installation:

```powershell
cloudflared tunnel --url http://127.0.0.1:7861
```

Put the generated URL into this Nightbot command, replacing `<public-host>`:

```text
$(urlfetch https://<public-host>/api/nightbot/ai?query=$(querystring)&viewer_id=$(userid)&viewer_name=$(querystring $(user)))
```

`$(querystring)` URL-encodes the viewer prompt and display name; `$(userid)`
provides a stable service-specific viewer ID for the one-minute cooldown. The
responder enforces a 280-character hard cap, below Nightbot's 400-character
URLFetch response limit. [Nightbot QueryString](https://docs.nightbot.tv/variables/querystring),
[Nightbot User](https://docs.nightbot.tv/variables/user),
[Nightbot UserID](https://docs.nightbot.tv/variables/userid), and
[Nightbot UrlFetch](https://docs.nightbot.tv/variables/urlfetch)

Nightbot sends a `Nightbot-User` header for a viewer-run URLFetch command. The
public route uses that documented header when it is valid. If the header is
missing or malformed, it falls back to `viewer_id` and `viewer_name` from the
command above. It returns `404 Not found` only when neither source identifies a
viewer. The fallback keeps ordinary commands working, but it is not
cryptographic authentication: callers who know the public URL can forge query
parameters. Keep the tunnel URL private and rotate it if it leaks.

The viewer prompt is present in the URL sent to Nightbot and to whichever
tunnel, VPN, proxy, or host you choose. This app disables Uvicorn access logs
and its own logs never write prompts, replies, URLs, headers, or API keys, but
those external services have their own data-handling policies.

Cloudflare Quick Tunnels have temporary `trycloudflare.com` URLs that change on
restart, so update the Nightbot command whenever one changes. A named tunnel,
VPN, reverse proxy, or VPS can provide a stable endpoint. [Cloudflare Quick
Tunnel documentation](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/do-more-with-tunnels/trycloudflare/)

## Safety Boundaries

- Local inference permits one active generation plus a small queue and uses a
  15-second response deadline.
- Cloud calls use a 15-second timeout and permit at most four in flight.
- Public Cloud API URLs require HTTPS. Explicit localhost, `.local`, `.internal`,
  and private/LAN addresses may use HTTP for a self-hosted provider.
- SQLite holds settings, cooldown records, and the activity feed. If its folder
  becomes temporarily unwritable, replies keep working with Local defaults and
  in-memory cooldowns; the Status field says `Temporary memory mode` and the
  app retries persistence every 30 seconds. If logs cannot be written either,
  diagnostics are skipped rather than blocking that fallback.
- Logs exclude prompts, responses, URLs, and secrets.

## Windows Releases

The release is a PyInstaller **one-folder** bundle wrapped by Inno Setup. Native
Vulkan and llama.cpp DLLs remain beside the executable rather than being hidden
inside one self-extracting binary.

```powershell
uv sync --group build
pwsh scripts/build_windows.ps1
```

The output is `dist\YT Livestream Chatbot\`. The signed GitHub Release process,
certificate secrets, and tag workflow are documented in
[docs/publishing.md](docs/publishing.md).

## Verify

```powershell
uv run python -m unittest discover -s tests -v
```
