
export default {
  async fetch(request: Request): Promise<Response> {
    const url = new URL(request.url);

    if (
      request.method === "GET" &&
      url.pathname === "/health"
    ) {
      return Response.json({
        status: "ok",
        service: "youtube-ai-relay",
      });
    }

    return new Response("Not Found", {
      status: 404,
    });
  },
};
