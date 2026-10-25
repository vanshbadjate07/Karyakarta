// Starts the Karyakarta service for the desktop app and stops it again on quit.
const { spawn, execFileSync } = require("node:child_process");
const crypto = require("node:crypto");
const net = require("node:net");
const path = require("node:path");

function freePort() {
  return new Promise((resolve, reject) => {
    const server = net.createServer();
    server.once("error", reject);
    server.listen(0, "127.0.0.1", () => {
      const { port } = server.address();
      server.close(() => resolve(port));
    });
  });
}

async function waitForHealth(baseUrl, child, getLog, timeoutMs = 90000) {
  const started = Date.now();
  while (Date.now() - started < timeoutMs) {
    if (child.exitCode !== null) throw new Error(`The Karyakarta service stopped while starting.\n${getLog()}`);
    try {
      const res = await fetch(`${baseUrl}/api/health`);
      if (res.ok) return;
    } catch {
      /* not up yet */
    }
    await new Promise((r) => setTimeout(r, 400));
  }
  throw new Error(`The Karyakarta service did not start in time.\n${getLog()}`);
}

async function startBackend() {
  const dir = process.env.KARYAKARTA_BACKEND_DIR || path.resolve(__dirname, "..", "..", "Backend");
  const python =
    process.env.KARYAKARTA_PYTHON || path.join(dir, ".venv", process.platform === "win32" ? "Scripts" : "bin", process.platform === "win32" ? "python.exe" : "python");
  const port = await freePort();
  const token = crypto.randomBytes(32).toString("hex");
  const baseUrl = `http://127.0.0.1:${port}`;

  const child = spawn(python, ["-m", "karyakarta"], {
    cwd: dir,
    env: { ...process.env, KARYAKARTA_PORT: String(port), KARYAKARTA_API_TOKEN: token },
    stdio: ["ignore", "pipe", "pipe"],
    windowsHide: true,
  });
  let log = "";
  const keep = (chunk) => {
    log = (log + chunk.toString()).slice(-2000);
  };
  child.stdout.on("data", keep);
  child.stderr.on("data", keep);
  child.on("error", (err) => keep(`Could not start ${python}: ${err.message}`));

  try {
    await waitForHealth(baseUrl, child, () => log);
  } catch (err) {
    stop(child);
    throw err;
  }
  return { connection: { baseUrl, token }, stop: () => stop(child) };
}

function stop(child) {
  if (!child || child.exitCode !== null) return;
  try {
    if (process.platform === "win32") execFileSync("taskkill", ["/pid", String(child.pid), "/T", "/F"], { stdio: "ignore" });
    else child.kill("SIGTERM");
  } catch {
    /* already gone */
  }
}

module.exports = { startBackend };
