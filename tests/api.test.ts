import { describe, expect, it, vi } from "vitest";
import { Api, ApiError, errorMessage } from "../src/lib/api";

const conn = { baseUrl: "http://127.0.0.1:8765", token: "tok en" };
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

describe("error wording", () => {
  it("turns service errors into plain sentences", () => {
    expect(errorMessage(401, null)).toContain("Restart Karyakarta");
    expect(errorMessage(429, null)).toContain("Too many tasks");
    expect(errorMessage(422, { detail: "The starting address must be a normal website address." })).toContain("starting address");
    expect(errorMessage(422, { detail: [{ loc: ["body", "instruction"], msg: "too short" }] })).toContain("Describe the task");
    expect(errorMessage(500, null)).toContain("500");
  });
});

describe("Api", () => {
  it("sends the access token on every request and the task as JSON", async () => {
    const fetchFn = vi.fn().mockResolvedValue(json({ id: 4 }));
    const api = new Api(conn, fetchFn as unknown as typeof fetch);
    await api.createTask("Find a price", "  example.com ");
    const [url, init] = fetchFn.mock.calls[0];
    expect(url).toBe("http://127.0.0.1:8765/api/tasks");
    expect(init.headers["X-Karyakarta-Token"]).toBe("tok en");
    expect(JSON.parse(init.body)).toEqual({ instruction: "Find a price", start_url: "example.com" });
    await api.createTask("Do it", "   ");
    expect(JSON.parse(fetchFn.mock.calls[1][1].body).start_url).toBeNull();
  });

  it("reports a stopped service and service errors clearly", async () => {
    const down = new Api(conn, vi.fn().mockRejectedValue(new TypeError("fetch failed")) as unknown as typeof fetch);
    await expect(down.status()).rejects.toThrow("Cannot reach the Karyakarta service");
    const bad = new Api(conn, vi.fn().mockResolvedValue(json({ detail: "Task not found." }, 404)) as unknown as typeof fetch);
    await expect(bad.getTask(9)).rejects.toMatchObject({ status: 404, message: "Task not found." });
    expect(new ApiError(1, "x").name).toBe("ApiError");
  });

  it("builds the live stream address with the token encoded", () => {
    const api = new Api(conn);
    expect(api.streamUrl(7, 12)).toBe("ws://127.0.0.1:8765/api/ws/tasks/7?token=tok%20en&after=12");
  });

  it("sends a secret only to the credential route", async () => {
    const fetchFn = vi.fn().mockResolvedValue(json({ ok: true }));
    const api = new Api(conn, fetchFn as unknown as typeof fetch);
    await api.sendCredential(3, "s3cret");
    expect(fetchFn.mock.calls[0][0]).toBe("http://127.0.0.1:8765/api/tasks/3/credential");
    expect(JSON.parse(fetchFn.mock.calls[0][1].body)).toEqual({ value: "s3cret" });
  });

  it("streams the model download and surfaces a failure", async () => {
    const stream = (lines: string[]) => new Response(new ReadableStream({ start(c) { c.enqueue(new TextEncoder().encode(lines.join("\n") + "\n")); c.close(); } }), { status: 200 });
    const seen: (number | null)[] = [];
    const ok = new Api(conn, vi.fn().mockResolvedValue(stream(['{"status":"pulling","percent":10}', '{"status":"pulling","percent":100}', '{"status":"success","percent":100}'])) as unknown as typeof fetch);
    await ok.pullModel((p) => seen.push(p.percent));
    expect(seen).toEqual([10, 100, 100]);
    const failing = new Api(conn, vi.fn().mockResolvedValue(stream(['{"status":"error","percent":null,"error":"The local AI engine is not running."}'])) as unknown as typeof fetch);
    await expect(failing.pullModel(() => undefined)).rejects.toThrow("not running");
  });
});
