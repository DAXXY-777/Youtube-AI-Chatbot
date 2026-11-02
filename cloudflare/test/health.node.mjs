
import test from "node:test";
import assert from "node:assert/strict";
import worker from "../src/index.ts";

test("GET /health returns healthy status", async () => {
  const request = new Request("http://localhost/health");

  const response = await worker.fetch(request);

  assert.equal(response.status, 200);

  const body = await response.json();

  assert.deepEqual(body, {
    status: "ok",
    service: "youtube-ai-relay",
  });
});

test("Unknown routes return 404", async () => {
  const request = new Request("http://localhost/unknown");

  const response = await worker.fetch(request);

  assert.equal(response.status, 404);
  assert.equal(await response.text(), "Not Found");
});

test("POST /health is not allowed", async () => {
  const request = new Request("http://localhost/health", {
    method: "POST",
  });

  const response = await worker.fetch(request);

  assert.equal(response.status, 404);
});
