
export default {
  async fetch(request: Request): Promise<Response> {
    const url = new URL(request.url);

    // Health check endpoint
    if (request.method === "GET" && url.pathname === "/health") {
      return Response.json({
        status: "ok",
        service: "youtube-ai-relay",
      });
    }

    // Return 404 for unknown endpoints
    return new Response("Not Found", {
      status: 404,
    });
  },
};
