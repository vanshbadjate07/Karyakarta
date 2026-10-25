const { app, BrowserWindow, ipcMain, session, shell, dialog } = require("electron");
const path = require("node:path");
const { startBackend } = require("./backend.cjs");

const SMOKE = process.argv.includes("--smoke");
const DEV_URL = process.env.KARYAKARTA_DEV_URL; // e.g. http://127.0.0.1:5173 while developing the interface
const ALLOWED_LINKS = /^https:\/\/ollama\.com\//;

let backend = null;
let connection = null;
let win = null;

if (!app.requestSingleInstanceLock()) {
  app.quit();
} else {
  app.on("second-instance", () => {
    if (win) {
      if (win.isMinimized()) win.restore();
      win.focus();
    }
  });
}

async function resolveBackend() {
  if (process.env.KARYAKARTA_URL && process.env.KARYAKARTA_API_TOKEN) {
    connection = { baseUrl: process.env.KARYAKARTA_URL, token: process.env.KARYAKARTA_API_TOKEN };
    return;
  }
  backend = await startBackend();
  connection = backend.connection;
}

function createWindow() {
  win = new BrowserWindow({
    width: 1320,
    height: 860,
    minWidth: 900,
    minHeight: 600,
    show: false,
    backgroundColor: "#f7f6f3",
    title: "Karyakarta",
    webPreferences: {
      preload: path.join(__dirname, "preload.cjs"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  });
  win.once("ready-to-show", () => win.show());

  const origin = DEV_URL ? new URL(DEV_URL).origin : "file://";
  win.webContents.setWindowOpenHandler(() => ({ action: "deny" }));
  win.webContents.on("will-navigate", (event, url) => {
    if (!url.startsWith(origin)) event.preventDefault();
  });

  if (DEV_URL) win.loadURL(DEV_URL);
  else win.loadFile(path.join(__dirname, "..", "dist", "index.html"));
  return win;
}

ipcMain.handle("karyakarta:connection", () => connection);
ipcMain.handle("karyakarta:open-external", (_event, url) => {
  if (typeof url === "string" && ALLOWED_LINKS.test(url)) return shell.openExternal(url);
});

// Checks the whole chain: service started, interface loaded, bridge works, service answers.
async function smokeTest(window) {
  const script = `(async () => {
    const conn = await window.karyakarta.getConnection();
    const res = await fetch(conn.baseUrl + "/api/system/status", { headers: { "X-Karyakarta-Token": conn.token } });
    const status = await res.json();
    for (let i = 0; i < 50 && !document.body.innerText.includes("What shall I take care of?"); i++) await new Promise((r) => setTimeout(r, 200));
    return { statusCode: res.status, hasService: !!status.version, homeShown: document.body.innerText.includes("What shall I take care of?"), nodeLeaked: typeof require !== "undefined" || typeof process !== "undefined" };
  })()`;
  try {
    const result = await window.webContents.executeJavaScript(script);
    console.log("SMOKE_RESULT " + JSON.stringify(result));
    return result.statusCode === 200 && result.hasService && result.homeShown && !result.nodeLeaked ? 0 : 1;
  } catch (err) {
    console.log("SMOKE_ERROR " + err.message);
    return 1;
  }
}

app.whenReady().then(async () => {
  session.defaultSession.setPermissionRequestHandler((_wc, _permission, callback) => callback(false));
  try {
    await resolveBackend();
  } catch (err) {
    if (SMOKE) {
      console.log("SMOKE_ERROR " + err.message);
      return app.exit(1);
    }
    dialog.showErrorBox("Karyakarta could not start", String(err.message));
    return app.quit();
  }
  const window = createWindow();
  if (SMOKE) {
    window.webContents.once("did-finish-load", async () => app.exit(await smokeTest(window)));
  }
});

app.on("window-all-closed", () => app.quit());
app.on("will-quit", () => {
  if (backend) backend.stop();
});
