
import asyncio
from pathlib import Path

from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed, InvalidStatus


WS_URL = "ws://127.0.0.1:8787/ws"

# Read the local development token without printing it.
ENV_FILE = Path(__file__).resolve().parents[1] / ".dev.vars"


def load_token() -> str:
    if not ENV_FILE.is_file():
        raise RuntimeError("Missing cloudflare/.dev.vars")

    for line in ENV_FILE.read_text(encoding="utf-8-sig").splitlines():
        key, separator, value = line.strip().partition("=")

        if separator and key == "RELAY_DEV_TOKEN":
            token = value.strip().strip('"').strip("'")
            if token:
                return token

    raise RuntimeError("RELAY_DEV_TOKEN is missing")


async def test_invalid_token() -> None:
    try:
        async with connect(
            WS_URL,
            additional_headers={
                "Authorization": "Bearer intentionally-invalid-token"
            },
            open_timeout=10,
        ):
            raise AssertionError("Invalid token was accepted!")

    except InvalidStatus as error:
        assert error.response.status_code == 401, (
            f"Expected HTTP 401, got {error.response.status_code}"
        )
        print("PASS: Invalid token rejected (401)")


async def test_valid_connection(token: str) -> None:
    async with connect(
        WS_URL,
        additional_headers={
            "Authorization": f"Bearer {token}"
        },
        open_timeout=10,
    ) as websocket:
        assert websocket.response.status_code == 101
        print("PASS: Authenticated WebSocket connected (101)")

        await websocket.send("test-message")

        try:
            await asyncio.wait_for(websocket.recv(), timeout=10)

        except ConnectionClosed as error:
            close_code = error.rcvd.code if error.rcvd else None

            assert close_code == 1008, (
                f"Expected close code 1008, got {close_code}"
            )

            print("PASS: Durable Object rejected test message (1008)")
        else:
            raise AssertionError("Expected the relay to close the connection")


async def test_message_round_trip(token: str) -> None:
    async with connect(
        WS_URL,
        additional_headers={
            "Authorization": f"Bearer {token}"
        },
        open_timeout=10,
    ) as websocket:
        await websocket.send("relay-probe-v1")

        response = await asyncio.wait_for(
            websocket.recv(),
            timeout=10,
        )

        assert response == "relay-ack-v1", (
            f"Unexpected response: {response!r}"
        )

        print("PASS: Bidirectional WebSocket messaging")

async def main() -> None:
    token = load_token()

    await test_invalid_token()
    await test_valid_connection(token)
    await test_message_round_trip(token)

    print("\nAll WebSocket checks passed!")


if __name__ == "__main__":
    asyncio.run(main())
