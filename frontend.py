import gradio as gr

from api_client import stream_chat


def display_chat(url: str):

    if not url.strip():
        yield "Please enter a YouTube livestream URL."
        return

    messages = []

    yield "Connecting..."

    try:

        for event in stream_chat(url):

            event_type = event.get("type")

            # Normal chat message
            if event_type == "chat":

                data = event["data"]

                author = data["author"]
                message = data["message"]

                messages.append(
                    f"{author}: {message}"
                )

                # Prevent unlimited memory growth.
                messages = messages[-500:]

                yield "\n".join(messages)

            # Backend reported an error
            elif event_type == "error":

                error_message = event.get(
                    "message",
                    "Unknown error",
                )

                messages.append(
                    f"[ERROR] {error_message}"
                )

                yield "\n".join(messages)
                return

            # Livestream/chat ended
            elif event_type == "end":

                messages.append(
                    "[Stream ended]"
                )

                yield "\n".join(messages)
                return

    except Exception as exc:

        yield f"Could not connect to backend:\n{exc}"


with gr.Blocks() as app:

    gr.Markdown("# YouTube Live Chat")

    url = gr.Textbox(
        label="YouTube Livestream",
        placeholder="Paste YouTube livestream link...",
    )

    start = gr.Button(
        "Start",
        variant="primary",
    )

    chat_box = gr.Textbox(
        label="Live Chat",
        lines=20,
        interactive=False,
    )

    start.click(
        fn=display_chat,
        inputs=url,
        outputs=chat_box,
    )


app.queue().launch()