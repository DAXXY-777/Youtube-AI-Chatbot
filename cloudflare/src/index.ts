
import httpHandler from "./http-handler";

export { RelayRoom } from "./relay-room";

interface WorkerBindings {
  RELAY_ROOM: DurableObjectNamespace;
  RELAY_DEV_TOKEN?: string;
}

export default {
  async fetch(
    request: Request,
    env: WorkerBindings
  ): Promise<Response> {
    const url = new URL(request.url);

    // Preserve existing HTTP endpoints.
    if (url.pathname !== "/ws") {
      return httpHandler.fetch(request);
    }

    // WebSocket upgrades must use GET.
    if (request.method !== "GET") {
      return new Response("Method Not Allowed", {
        status: 405,
      });
    }

    if (
      request.headers.get("Upgrade")?.toLowerCase() !==
      "websocket"
    ) {
      return new Response("WebSocket upgrade required", {
        status: 426,
      });
    }

    // Fail closed when authentication isn't configured.
    if (!env.RELAY_DEV_TOKEN) {
      return new Response("Relay unavailable", {
        status: 503,
      });
    }

    if (
      request.headers.get("Authorization") !==
      `Bearer ${env.RELAY_DEV_TOKEN}`
    ) {
      return new Response("Unauthorized", {
        status: 401,
      });
    }

    // Temporary single-room routing for local development.
    const room = env.RELAY_ROOM.getByName("local-test");

    // Forward the WebSocket upgrade to the Durable Object.
    return room.fetch(request);
  },
};
