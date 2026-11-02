
import { SELF } from "cloudflare:test";
import { describe, it, expect } from "vitest";

describe("YouTube AI Relay Worker", () => {
  it("GET /health returns healthy status", async () => {
    const response = await SELF.fetch(
      "http://example.com/health"
    );

    expect(response.status).toBe(200);

    expect(await response.json()).toEqual({
      status: "ok",
      service: "youtube-ai-relay",
    });
  });

  it("unknown routes return 404", async () => {
    const response = await SELF.fetch(
      "http://example.com/unknown"
    );

    expect(response.status).toBe(404);
    expect(await response.text()).toBe("Not Found");
  });

  it("POST /health returns 404", async () => {
    const response = await SELF.fetch(
      "http://example.com/health",
      { method: "POST" }
    );

    expect(response.status).toBe(404);
  });
});
