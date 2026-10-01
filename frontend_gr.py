"""The small Gradio control surface for YT Livestream Chatbot."""

from __future__ import annotations

from html import escape

import gradio as gr

from chat_service import chat_service
from model_presets import PRESET_MODELS
from model_runtime import local_model_runtime
from runtime_service import CLOUD_MODE, LOCAL_MODE, RuntimeSettings, ViewerIdentity, runtime_service


APP_TITLE = "YT Livestream Chatbot"


def render_activity() -> str:
    """Render the active stream's Nightbot exchanges as read-only chat bubbles."""
    _stream, entries = runtime_service.list_activity()
    if not entries:
        return '<p class="empty-feed">Waiting for a !AI message.</p>'
    return "".join(
        f"""
        <article class="activity-entry">
            <p class="activity-prompt"><strong>{escape(entry.viewer)}</strong>: !AI {escape(entry.prompt)}</p>
            <p class="activity-response">{escape(entry.response)}</p>
        </article>
        """
        for entry in entries
    )


def status_for(_settings: RuntimeSettings) -> str:
    return f"{runtime_service.runtime_status()} | Ambient: {chat_service.memory.listener_status()}"


def mode_value(settings: RuntimeSettings) -> str:
    return "Cloud" if settings.active_mode == CLOUD_MODE else "Local"


def show_mode(mode: str):
    settings = runtime_service.save_mode(mode)
    return (
        gr.update(visible=settings.active_mode == LOCAL_MODE),
        gr.update(visible=settings.active_mode == CLOUD_MODE),
        status_for(settings),
    )


def load_settings():
    """Fill controls without ever reading the Cloud secret back out."""
    settings = runtime_service.get_settings()
    return (
        mode_value(settings),
        settings.local_preset_label,
        settings.cloud_base_url or "",
        "",
        settings.cloud_model_id or "",
        settings.active_stream_url or "",
        status_for(settings),
        gr.update(visible=settings.active_mode == LOCAL_MODE),
        gr.update(visible=settings.active_mode == CLOUD_MODE),
        render_activity(),
    )


def select_local_model(preset_label: str):
    settings = runtime_service.save_local_settings(preset_label)
    return status_for(settings)


def download_selected_model(preset_label: str):
    runtime_service.save_local_settings(preset_label)
    local_model_runtime.start_download_and_load(preset_label)
    return status_for(runtime_service.get_settings())


def save_cloud_settings(base_url: str, api_key: str, model_id: str):
    try:
        settings = runtime_service.save_cloud_settings(base_url, api_key, model_id)
    except Exception as error:
        return "", f"Cloud settings not saved: {error}"
    return "", status_for(settings)


def set_active_stream(youtube_url: str):
    try:
        settings = runtime_service.set_active_stream(youtube_url)
    except ValueError as error:
        return f"Stream not set: {error}", render_activity()
    chat_service.set_active_stream(settings.active_stream_url, force=True)
    stream_status = "Stream set." if settings.active_stream_url else "No stream selected."
    return f"{stream_status} {status_for(settings)}", render_activity()


CONSOLE_TEST_VIEWER = ViewerIdentity(
    identity_key="console-test",
    provider="console",
    provider_id="test",
    username="Console test",
    display_name="Console test",
    user_level="owner",
)


def test_ai(test_prompt: str):
    prompt = test_prompt.strip() or "Say hello to the stream in one short sentence."
    try:
        response = chat_service.respond(
            runtime_service.get_request_context(), CONSOLE_TEST_VIEWER, prompt
        )
    except Exception:
        response = "AI is unavailable right now."
    return response, status_for(runtime_service.get_settings())


def refresh_console():
    settings = runtime_service.get_settings()
    return render_activity(), status_for(settings)


CSS = """
.gradio-container {
    max-width: 1280px !important;
    margin: 0 auto !important;
    padding: 28px 32px !important;
}
#console-layout {
    align-items: flex-start;
    gap: 18px;
}
#settings-sidebar > .gap,
#runtime-sidebar > .gap,
#activity-panel > .gap {
    gap: 14px;
}
#chat-feed {
    border: 1px solid var(--border-color-primary);
    background: var(--block-background-fill);
    min-height: 520px;
    max-height: 520px;
    overflow-y: auto;
    padding: 16px;
}
#chat-feed .activity-entry {
    display: grid;
    gap: 12px;
    margin-bottom: 20px;
}
#chat-feed .activity-entry:last-child {
    margin-bottom: 0;
}
#chat-feed .activity-prompt,
#chat-feed .activity-response {
    width: fit-content;
    max-width: 82%;
    margin: 0;
    padding: 10px 12px;
    border: 1px solid var(--border-color-primary);
    line-height: 1.45;
}
#chat-feed .activity-prompt {
    justify-self: end;
    background: var(--input-background-fill);
}
#chat-feed .activity-response {
    justify-self: start;
}
#chat-feed .empty-feed {
    margin: 0;
    color: var(--body-text-color-subdued);
}
#runtime-status textarea {
    font-family: inherit;
    min-height: 38px !important;
}
@media (max-width: 760px) {
    .gradio-container {
        padding: 20px !important;
    }
    #console-layout {
        gap: 14px;
    }
}
"""


with gr.Blocks(title=APP_TITLE) as demo:
    gr.Markdown(f"# {APP_TITLE}")
    with gr.Row(elem_id="console-layout"):
        with gr.Column(scale=3, min_width=280, elem_id="settings-sidebar"):
            mode = gr.Radio(
                choices=["Local", "Cloud"], value="Local", label="AI mode"
            )
            with gr.Column(visible=True) as local_settings:
                local_model = gr.Dropdown(
                    choices=[preset.label for preset in PRESET_MODELS],
                    value=PRESET_MODELS[0].label,
                    label="Local model",
                )
                download_model_button = gr.Button("Download model")
            with gr.Column(visible=False) as cloud_settings:
                cloud_base_url = gr.Textbox(
                    label="OpenAI-compatible API URL",
                    placeholder="https://api.example.com/v1",
                )
                cloud_api_key = gr.Textbox(label="API key", type="password")
                cloud_model_id = gr.Textbox(label="Model ID", placeholder="provider-model-name")
                save_cloud_button = gr.Button("Save Cloud settings")

        with gr.Column(scale=7, min_width=440, elem_id="activity-panel"):
            with gr.Row():
                youtube_url = gr.Textbox(
                    label="YouTube live URL",
                    placeholder="https://www.youtube.com/watch?v=<video-id>",
                    scale=5,
                )
                set_stream_button = gr.Button("Set stream", scale=1)
            gr.Markdown("### Incoming messages")
            activity_feed = gr.HTML(
                value='<p class="empty-feed">Waiting for a !AI message.</p>',
                elem_id="chat-feed",
            )

        with gr.Column(scale=3, min_width=280, elem_id="runtime-sidebar"):
            test_prompt = gr.Textbox(
                value="Say hello to the stream in one short sentence.",
                label="Test prompt",
                lines=2,
            )
            test_button = gr.Button("Test AI", variant="secondary")
            test_reply = gr.Textbox(label="Test reply", interactive=False, lines=3)
            runtime_status = gr.Textbox(
                value="No model loaded",
                label="Status",
                interactive=False,
                lines=1,
                elem_id="runtime-status",
            )

    mode.change(
        show_mode,
        inputs=mode,
        outputs=[local_settings, cloud_settings, runtime_status],
    )
    local_model.change(select_local_model, inputs=local_model, outputs=runtime_status)
    download_model_button.click(
        download_selected_model, inputs=local_model, outputs=runtime_status
    )
    save_cloud_button.click(
        save_cloud_settings,
        inputs=[cloud_base_url, cloud_api_key, cloud_model_id],
        outputs=[cloud_api_key, runtime_status],
    )
    set_stream_button.click(
        set_active_stream,
        inputs=youtube_url,
        outputs=[runtime_status, activity_feed],
    )
    test_button.click(
        test_ai, inputs=test_prompt, outputs=[test_reply, runtime_status]
    )
    demo.load(
        load_settings,
        outputs=[
            mode,
            local_model,
            cloud_base_url,
            cloud_api_key,
            cloud_model_id,
            youtube_url,
            runtime_status,
            local_settings,
            cloud_settings,
            activity_feed,
        ],
    )
    refresh_timer = gr.Timer(value=2)
    refresh_timer.tick(refresh_console, outputs=[activity_feed, runtime_status])


def build_ui() -> gr.Blocks:
    """Return the UI for mounting into the FastAPI application."""
    return demo
