# YT Livestream Chatbot: Interview and Maintenance Cheat Sheet

This guide explains the project as it is implemented today. Use it to prepare
for interviews, investigate problems, and make focused changes. For a longer
function-by-function tour, also read `docs/application-guide.md`.

## The Project in One Sentence

YT Livestream Chatbot is a Windows desktop app that routes Nightbot `!AI`
commands to a local GGUF model or OpenAI-compatible Cloud model, while keeping
the settings UI private on the streamer's computer.

## 30-Second Interview Answer

"I built a local desktop chatbot for YouTube livestreams. Nightbot calls one
small FastAPI endpoint when a viewer uses `!AI`. The app validates viewer
identity, applies a per-viewer cooldown, builds a short prompt with optional
recent public chat context, and returns a plain-text response sized for YouTube
chat. I separated the private Gradio UI from the tunnelable API, used SQLAlchemy
and SQLite for local state, stored Cloud keys in Windows Credential Manager, and
packaged the application with PyInstaller and Inno Setup."

Be precise: it is not a hosted multi-tenant service, and its public endpoint is
a narrow private capability rather than strongly authenticated public API.

## Five-Minute Architecture Walkthrough

1. `desktop.py` starts two loopback-only Uvicorn servers and opens the UI in a
   pywebview window.
2. Port `7860` hosts Gradio, the private settings UI. It is never tunneled.
3. Port `7861` exposes only `GET /api/nightbot/ai`. A user-managed tunnel or
   proxy may forward to this port.
4. A Nightbot URLFetch request reaches FastAPI. `api.py` validates the viewer
   identity from the `Nightbot-User` header or command fallback parameters.
5. `RuntimeService` claims a one-minute per-viewer cooldown and takes a
   snapshot of the saved mode, model/provider config, and stream context.
6. `ChatService` gets an immediate snapshot of Ambient Memory, then chooses a
   local or Cloud responder.
7. The responder creates a bounded prompt, asks for at most 75 tokens, and
   clips the plain-text response to 280 characters.
8. The response returns to Nightbot. SQLite activity recording happens after
   generation, so a database write failure cannot break the chat reply.

```text
Desktop window -> pywebview -> private Gradio UI :7860
                                      |
                                      v
                    RuntimeService <-> SQLite via SQLAlchemy
                         |      |
                         |      +-> Windows Credential Manager for Cloud key
                         v
                    ChatService -> AmbientMemory -> pytchat-ng -> YouTube
                         |
                         +-> LocalResponder -> llama-cpp-python -> GGUF
                         |
                         +-> CloudResponder -> OpenAI-compatible provider

Viewer -> YouTube -> Nightbot -> tunnel/proxy -> FastAPI API :7861
                                                /api/nightbot/ai
```

## Nightbot Request Flow

The Nightbot command is:

```text
$(urlfetch https://<public-host>/api/nightbot/ai?query=$(querystring)&viewer_id=$(userid)&viewer_name=$(querystring $(user)))
```

`query` is the viewer prompt. `viewer_id` is the stable cooldown key. The route
prefers Nightbot's `Nightbot-User` header, then uses the two fallback parameters
when that header is missing or invalid. It returns `404 Not found` only when
neither identity source is valid.

`claim_viewer_cooldown()` writes the viewer's last accepted timestamp before
inference begins. That ordering prevents two nearly simultaneous requests from
both passing the cooldown.

Ambient Memory returns up to the latest 85 normal public chat messages. It
excludes `!AI` commands, removes duplicate message IDs, and is deliberately not
stored in SQLite. If YouTube listening fails, the current viewer query still
receives a response with no ambient context.

`prompting.py` labels ambient messages as untrusted background context, then
adds the current viewer question separately. It limits output by token count and
by character count because tokens are not characters.

## Module Map

| Module | Ownership |
| --- | --- |
| `desktop.py` | Desktop window, startup, shutdown, single-instance behavior. |
| `main.py` | Composition root; creates private UI and public API applications. |
| `api.py` | HTTP parsing, identity selection, response status and headers. |
| `runtime_service.py` | Settings, cooldowns, stream contexts, persistence fallback. |
| `database.py` / `orm_models.py` | SQLAlchemy engine, sessions, and ORM entity mappings. |
| `secret_store.py` | Cloud secret interface and Credential Manager adapter. |
| `frontend_gr.py` | Private Gradio settings controls and read-only activity feed. |
| `model_presets.py` | Curated repo and GGUF filename allowlist. |
| `model_runtime.py` | Model download, load, safe replacement, and local generation. |
| `inference_control.py` | Bounded single-worker queue for local inference. |
| `responders.py` | Local and Cloud provider adapters. |
| `chat_service.py` | Chooses a responder and hands it memory context. |
| `memory.py` | YouTube listener and bounded in-memory chat buffer. |
| `prompting.py` | Prompt assembly and final reply cleanup. |
| `network_safety.py` | Validates provider base URLs. |
| `logging_config.py` | Bounded, privacy-conscious diagnostic logs. |

## Local Model Lifecycle

1. The UI reads preset labels from `model_presets.py`.
2. The user selects one and clicks `Download model`.
3. `LocalModelRuntime.start_download_and_load()` starts a daemon worker so the
   UI and Nightbot route are not blocked.
4. The runtime calculates this exact file location:

   ```text
   models/<repository-with-slash-replaced-by-->/<filename>.gguf
   ```

5. It checks `Path.is_file()`. If the GGUF exists, Hugging Face is skipped. If
   absent, `hf_hub_download()` fetches only the allowlisted repository/file pair.
6. `llama_cpp.Llama` loads the GGUF with Vulkan offload when available, or CPU
   fallback otherwise.
7. A generation lock prevents an active model from being closed during a reply.
   If a replacement fails, the runtime attempts to restore the prior model.

Use these terms carefully:

- **Downloaded** means the GGUF exists on disk.
- **Loaded** means llama.cpp has instantiated it in RAM or VRAM.

The downloaded file survives restart. The loaded model does not. Clicking
`Download model` after restart detects the cached file and loads it without
downloading again. The current cache check only tests file presence; verifying a
published file hash would be a worthwhile hardening improvement.

## Persistence, Secrets, and Failure Modes

SQLite is appropriate for one streamer running a local desktop app: it needs no
database server and is easy to back up. SQLAlchemy maps these entities:

- `RuntimeConfiguration`: one saved Local/Cloud configuration.
- `StreamContext`: a YouTube URL or a process-specific `No stream N` group.
- `Viewer`: stable identity and last accepted request timestamp.
- `NightbotRequest`: persisted activity-feed history.

The Cloud key is not a SQLite column. `WindowsCredentialStore` stores it in
Windows Credential Manager. SQLite contains only whether a key exists, and the
UI never reads an old key back into the browser.

When SQLite cannot start or later fails, `RuntimeService` enters `Temporary
memory mode`: it uses Local defaults and in-memory cooldowns, while continuing
to serve replies. This favors core chatbot availability over activity history.

| Risk | Current behavior | Honest limitation |
| --- | --- | --- |
| Several local requests | Single worker with bounded queue. | Native inference cannot be safely force-cancelled mid-call. |
| Local model switch | Generation lock protects the old model. | Only one local model remains loaded. |
| Slow Cloud provider | 15-second timeout, maximum four requests in flight. | No provider billing guard or retry policy. |
| YouTube listener failure | Reconnects after 30 seconds; query still works. | `pytchat-ng` can break with upstream YouTube changes. |
| SQLite write failure | Reply returns and activity write is skipped. | History can be missing during the outage. |
| Duplicate desktop launch | Windows mutex rejects it. | Windows-specific behavior. |

## Security Story

Say this in an interview: "I treated the public URL as a narrow private
capability, not as a complete authentication system. I reduced attack surface
by exposing only the Nightbot route, isolating Gradio on a loopback listener,
validating input shapes and lengths, adding cooldowns, limiting prompt and reply
sizes, disabling access logs, and keeping secrets out of SQLite and normal
logs."

Remember these facts:

- Tunnel `7861`, never the Gradio UI on `7860`.
- Fallback identity parameters can be forged by anyone who learns the URL.
- Public Cloud providers require HTTPS. Explicit local/LAN providers may use
  HTTP for self-hosting.
- Quick Tunnel URLs are temporary and should be rotated if leaked.
- The public app does not mount Gradio, activity, or settings routes.

## Common Interview Questions

**Why FastAPI and Gradio together?** FastAPI owns HTTP boundaries and makes a
future frontend possible. Gradio made the first local settings UI fast to build
without adding a separate JavaScript application.

**Why separate the UI and public API into two apps?** The public listener does
not have private routes mounted at all. This is more dependable than merely
hiding a sensitive route behind UI navigation.

**Why SQLAlchemy rather than raw SQL?** It makes relations and transactions
clearer, keeps data access testable, and reduces repetitive mapping code. Raw
SQL would be viable for this small app, but the ORM scales better as concepts
such as viewers, stream contexts, and request history interact.

**How do you reduce prompt injection risk?** Ambient text is explicitly marked
untrusted, separated from the system prompt and current request, excludes `!AI`
commands, and is bounded by count and character budget. This reduces risk; it
does not make an LLM immune to prompt injection.

**How does cooldown survive a restart?** The service records last accepted time
in SQLite before inference. On restart the next request reads it. In-memory
cooldowns cover only the current session if SQLite is unavailable.

**How would you scale it?** Move inference to worker processes, replace SQLite
and local cooldown state with PostgreSQL or Redis, authenticate management
actions, introduce an owned domain/API gateway, and isolate model capacity and
configuration per streamer.

**What would you improve next?** Strong request authentication and rate limits
for broader public use; model file hash validation; and Alembic migrations.
`Base.metadata.create_all()` creates missing tables but does not safely evolve
existing user databases.

## Change Recipes

### Add a curated local model

1. Add a `ModelPreset` with label, Hugging Face repository ID, and exact GGUF
   filename in `model_presets.py`.
2. The Gradio dropdown updates because it reads `PRESET_MODELS`.
3. Add a test verifying the downloader receives the exact repository/file pair.
4. Run tests, then select and load the model.

Do not expose arbitrary model URLs through the public API.

### Change reply length or style

- `prompting.py`: `MAX_OUTPUT_TOKENS`, `MAX_REPLY_CHARACTERS`, `SYSTEM_PROMPT`.
- `model_runtime.py`: local `temperature` and `top_p`.
- `responders.py`: Cloud request payload and concurrency controls.

Keep the hard character cap below YouTube's chat limit.

### Change cooldown or ambient capacity

- `runtime_service.py`: `VIEWER_COOLDOWN`.
- `memory.py`: `AMBIENT_MEMORY_LIMIT`.
- `prompting.py`: `MAX_AMBIENT_MESSAGES` and
  `MAX_AMBIENT_CONTEXT_CHARACTERS`.

More context is not always better; it can crowd out the current viewer question.

### Add a public route

1. Put HTTP parsing and response decisions in `api.py`.
2. Put actual business behavior in a service or responder.
3. Mount it in `create_public_api_app()` only when it is truly safe to expose.
4. Define input limits and add FastAPI `TestClient` coverage.

### Replace Gradio with a real frontend

Keep the service layer, responders, ORM models, and Nightbot endpoint. Build a
separate authenticated management API for the new frontend. Do not reuse the
public Nightbot route for settings actions.

## Debugging Checklist

```powershell
uv sync --group build
uv run python -m unittest discover -s tests -v
uv run python main.py
```

```powershell
# Identify a process already using the local ports.
Get-NetTCPConnection -LocalPort 7860,7861 -ErrorAction SilentlyContinue

# Check the public API locally.
Invoke-WebRequest http://127.0.0.1:7861/health | Select-Object -Expand Content

# Read recent diagnostic metadata.
Get-Content logs\yt-livestream-chatbot.log -Tail 100
```

```powershell
# Exercise the Nightbot route locally using fallback identity fields.
Invoke-WebRequest `
  "http://127.0.0.1:7861/api/nightbot/ai?query=hello&viewer_id=local-test&viewer_name=Local%20Test" |
  Select-Object -Expand Content
```

Debug in this order: `/health`, local Nightbot route, tunnel target `7861`,
exact Nightbot command, logs, then model status. A Local model must display
`Model loaded: ...` before it can generate.

## Build and Release Facts

PyInstaller creates a one-folder bundle. Inno Setup packages it with a default
writable Documents install directory. The build command is:

```powershell
uv sync --group build
pwsh scripts/build_windows.ps1
```

The build script temporarily preserves `data`, `models`, and `logs`, rebuilds,
then restores them. This is why rebuilding does not make the user re-download a
cached GGUF. GitHub Actions tests pull requests, while a `v*` tag builds, signs,
packages, and publishes a release. See `docs/publishing.md` for the setup.

## Resume Bullet

Built a Windows desktop YouTube livestream chatbot using FastAPI, Gradio,
SQLAlchemy, SQLite, and llama.cpp; integrated Nightbot URLFetch, local GGUF
lifecycle, Cloud-provider secrets, and a signed PyInstaller/Inno Setup release
pipeline.

Use that sentence only if you can explain every term above.

## Study Order

1. Read this sheet for the narrative and design choices.
2. Read `docs/application-guide.md` while opening the modules named here.
3. Trace a request through `api.py`, `runtime_service.py`, `chat_service.py`,
   `responders.py`, and `prompting.py`.
4. Run the test suite and read the matching test before changing a module.
5. Practice the 30-second answer and question answers aloud.
