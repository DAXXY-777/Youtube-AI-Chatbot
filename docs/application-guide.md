# How YT Livestream Chatbot Works

This is a small desktop program, not a hosted web application. It opens a
private settings screen on the streamer's computer and exposes one separately
reachable HTTP endpoint only when the streamer creates a tunnel or another
network path to it.

```text
Viewer -> Nightbot -> public endpoint :7861 -> responder -> plain-text reply
Desktop WebView -> private Gradio UI :7860 -> same RuntimeService
```

Only `:7861` should be tunneled. The settings UI at `:7860` is loopback-only
and is not part of the public API.

## A Single `!AI` Request

1. A viewer types `!AI question` in YouTube chat.
2. Nightbot expands `$(querystring)`, sends a GET request to
   `/api/nightbot/ai?query=...`, and normally attaches its `Nightbot-User`
   header. The configured command also sends `viewer_id` and `viewer_name` as a
   fallback when that header is unavailable.
3. `api.py` validates the viewer identity, rejects a blank prompt with a short
   helpful message, and claims the viewer's one-minute cooldown.
4. `RuntimeService.get_request_context()` takes a snapshot of the saved Local
   or Cloud configuration plus the active stream.
5. `ChatService.respond()` takes an immediate snapshot of Ambient Memory. It
   never waits for YouTube chat.
6. A Local or Cloud responder builds a small prompt, calls the selected model,
   normalizes the result, and caps it at 280 characters.
7. The endpoint returns that plain text to Nightbot. It tries to save the
   activity record afterwards, but a SQLite failure cannot cancel the reply.

## Module And Function Map

### `app_paths.py`

`application_directory()` decides where user-owned files belong. In a source
run it is the project folder. In a PyInstaller release it is the folder
containing the installed `.exe`. The exported `DATA_DIRECTORY`,
`MODELS_DIRECTORY`, and `LOGS_DIRECTORY` keep all mutable files beside the
installed program rather than in AppData.

### `database.py` and `orm_models.py`

`Database` owns SQLAlchemy's engine and session factory. `initialize()` creates
the selected data directory and tables, enables SQLite foreign keys, and uses
write-ahead logging. Directory creation deliberately happens there, not during
Python import, so the program can fall back to temporary memory if the install
folder becomes unwritable.

`RuntimeConfiguration` is the single saved setting row. `StreamContext` groups
messages by stream URL or by a startup-only `No stream N` label. `Viewer` holds
Nightbot identity and the last accepted request time. `NightbotRequest` stores
the prompt, response, selected mode, viewer, and stream. `utc_now()` makes
timestamps consistent.

### `runtime_service.py`

`RuntimeService` is the shared application state layer. The UI and HTTP route
use the same instance instead of communicating through their own HTTP calls.

- `initialize()` creates the schema, creates this run's `No stream N` context,
  and removes request history older than 30 days.
- `get_settings()` and `get_request_context()` read a coherent settings or
  responder snapshot.
- `save_mode()`, `save_local_settings()`, and `save_cloud_settings()` validate
  and persist sidebar changes. Cloud validation happens before writing a new
  API key, so an invalid edit keeps the previous working setup.
- `set_active_stream()` accepts only
  `https://www.youtube.com/watch?v=<video-id>`, then activates or creates that
  stream context. Clearing it uses this process's `No stream N` context.
- `claim_viewer_cooldown()` atomically starts one viewer's one-minute window
  before inference. SQLite makes it survive a restart; an in-memory copy also
  protects the current session if SQLite is unavailable.
- `record_request()` and `list_activity()` power the center chat feed. A write
  error is caught so it can never turn a good bot reply into a failed request.

When SQLite cannot start or later errors, the service uses Local defaults and
temporary in-memory settings/cooldowns. `runtime_status()` labels this
`Temporary memory mode` and the next normal request retries database recovery
after 30 seconds.

### `api.py`

`_header_values()` parses Nightbot's URL-encoded header format, for example
`name=viewer&provider=youtube&providerId=123`. `viewer_from_header()` turns it
into `ViewerIdentity` for the cooldown and activity record.

`build_router()` creates the application routes:

- `GET /health` is a small local diagnostic.
- `GET /api/nightbot/ai?query=...` is the one endpoint intended for a tunnel.
  It prefers a valid Nightbot viewer header and falls back to command-supplied
  `viewer_id` and `viewer_name`; it returns `404 Not found` only when neither
  identity source is valid. It sets `Cache-Control: no-store`, applies cooldown,
  asks the responder, and best-effort records activity.
- `GET /api/activity` exists only on the private UI server and needs an
  explicit `NIGHTBOT_ACTIVITY_TOKEN` plus `X-Activity-Token`. The public API
  server does not mount it at all.

The header check is not a secret or a substitute for real authentication. It
is enough to reject accidental browser visits and Nightbot timer requests, but
someone who knows the public URL can forge headers. Treat the tunnel URL like a
private capability.

### `memory.py`

`extract_youtube_video_id()` accepts the exact watch URL form used by the UI.
`AmbientMemory.set_active_stream()` starts a daemon `pytchat-ng` listener, or
clears it when no stream is selected. The `force` option restarts the listener
when the user clicks Set stream again.

`_collect()` calls `pytchat.create(video_id=...)`, reads its `sync_items()`, and
reconnects every 30 seconds after a failure or ended chat. `ingest()` normalizes
viewer messages, ignores `!AI`, de-duplicates recent items, and retains only
the latest 85 messages. `snapshot()` returns the current buffer immediately,
which means YouTube chat failure never blocks an AI reply. `listener_status()`
provides the `Listening`, `Reconnecting`, or `No stream selected` text shown in
the existing Status field.

### `prompting.py`

`SYSTEM_PROMPT` defines the bot as a friendly, witty regular viewer, with
short plain-text replies and clear safety rules. `build_chat_messages()` creates
the exact model payload: system rules, optional recent chat labeled as untrusted
background context, and the viewer's current question. `shorten()` bounds each
input fragment. `clean_reply()` collapses whitespace and clips output to 280
characters. `MAX_OUTPUT_TOKENS` remains 75.

### `model_presets.py`, `model_runtime.py`, and `inference_control.py`

`model_presets.py` lists the exact GGUF repositories and filenames selectable
in the UI. It does not package models into the application.

`LocalModelRuntime.start_download_and_load()` launches a background worker so
the UI and Nightbot checks stay responsive. `_download_and_load()` uses
`huggingface_hub.hf_hub_download()` only for the selected curated file.
`_replace_loaded_model()` unloads the old model before loading the new one so
only one model occupies RAM or VRAM. `_restore_previous_model()` reloads the
old model if the new one fails. `generate()` sends the prompt to llama.cpp with
Vulkan GPU offload when supported and CPU otherwise.

`SingleWorkerInferenceQueue.run()` permits one local generation and a bounded
number of waiting requests. A call exceeding the 15-second deadline returns an
unavailable reply while its model slot remains reserved until that native call
finishes. `shutdown()` is restart-safe for closing and reopening the desktop
app in the same Python process.

### `responders.py` and `chat_service.py`

`ChatService.respond()` selects `LocalResponder` or `CloudResponder` from the
saved mode and hands it the already-collected ambient snapshot.

`LocalResponder.respond()` answers `Model not loaded.` until the chosen GGUF is
ready, then uses the single-worker queue. Native model failures become the
neutral `AI is unavailable right now.` message.

`CloudResponder.respond()` gets the API key from Credential Manager, verifies
that URL/model/key are configured, then calls the provider's OpenAI-compatible
`/chat/completions` route. It limits concurrent cloud requests to four and uses
a 15-second timeout. A public Cloud URL must be HTTPS. Local and LAN providers
can use HTTP by design.

### `frontend_gr.py`

`build_ui()` returns the one Gradio Blocks view. The left sidebar owns all
configuration controls, the center is the read-only incoming message feed, and
the right sidebar contains Test AI and Status.

`load_settings()` fills the controls without reading a stored API key back into
the browser. `show_mode()`, `select_local_model()`, `download_selected_model()`,
`save_cloud_settings()`, and `set_active_stream()` call the runtime service and
return just the component updates Gradio needs. `test_ai()` bypasses viewer
cooldown and activity history but uses the selected model/provider and current
ambient memory. `refresh_console()` updates the feed and Status every two
seconds.

### `main.py`, `desktop.py`, and `instance_guard.py`

`create_ui_app()` mounts Gradio on `127.0.0.1:7860`. `create_public_api_app()`
mounts only health and the Nightbot route on `127.0.0.1:7861`. Both call the
same lifespan setup. `ServerGroup` starts both loopback servers, suppresses
Uvicorn access logs so query prompts are not written, and gives a clear startup
error if either port is occupied.

`desktop.py` starts the servers, opens the private URL in pywebview's WebView2
window, and stops everything when it closes. `SingleInstanceGuard` uses a
Windows mutex to show a friendly message rather than launching a second
competing desktop process.

### `secret_store.py`, `network_safety.py`, and `logging_config.py`

`WindowsCredentialStore` writes only the Cloud API key to Windows Credential
Manager; SQLite has only an API-key-present boolean. `MemorySecretStore` is a
test replacement.

`validate_cloud_base_url()` accepts complete HTTP(S) URLs, requires HTTPS for
public hosts, and permits HTTP for explicit local or private LAN providers.
`configure_logging()` creates bounded rotating diagnostic logs. `log_event()`
accepts metadata only; calls intentionally exclude chat text, URLs, request
headers, and secrets. If the install folder cannot accept a log file, logging
uses a no-op handler so temporary-memory mode can still serve replies.

## What Leaves The Computer

Nightbot receives and URL-encodes the viewer query. Your chosen tunnel, VPN,
reverse proxy, or VPS receives the resulting request URL. The app itself avoids
access logging that query and does not send any traffic to a model provider in
Local mode. Cloud mode sends the bounded prompt and API key to the provider you
configured. YouTube Ambient Memory sends the public selected video ID to
YouTube through `pytchat-ng` and retains chat only in process memory.

## Tests And Release Files

The tests in `tests/` cover the request route, persistence, cooldown, fallback
mode, stream handling, model runtime behavior, reply limits, Cloud payloads,
and server separation. Run them with:

```powershell
uv run python -m unittest discover -s tests -v
```

`scripts/build_windows.ps1` makes the PyInstaller one-folder bundle.
`installer/YT-Livestream-Chatbot.iss` packages it with Inno Setup.
`.github/workflows/release-windows.yml` tests pull requests, then builds,
signs, and publishes a tagged release. [docs/publishing.md](publishing.md)
walks through the one-time GitHub setup and release process.
