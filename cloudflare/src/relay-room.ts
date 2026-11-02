
import { DurableObject } from "cloudflare:workers";

export class RelayRoom extends DurableObject {
  async fetch(request: Request): Promise<Response> {
    // Only accept WebSocket upgrade requests.
    if (
      request.headers.get("Upgrade")?.toLowerCase() !==
      "websocket"
    ) {
      return new Response("WebSocket upgrade required", {
        status: 426,
      });
    }

    // Create the two ends of the WebSocket.
    const pair = new WebSocketPair();
    const [client, server] = Object.values(pair);

    // Hibernation-compatible WebSocket registration.
    this.ctx.acceptWebSocket(server);

    return new Response(null, {
      status: 101,
      webSocket: client,
    });
  }

  // Until we implement authentication and the relay
  // protocol, reject incoming application messages.
  
    webSocketMessage(
    ws: WebSocket,
    message: string | ArrayBuffer
    ): void {
    // Temporary local development probe.
    if (message === "relay-probe-v1") {
        ws.send("relay-ack-v1");
        return;
    }

    // All other messages remain rejected.
    ws.close(1008, "Relay protocol not enabled");
    }

}
