/**
 * HelpDesk en Electron: carga la misma UI que el navegador (chat + tickets, modo claro)
 * con preload para ejecutar planes de escritorio (ratón/teclado) vía IPC.
 *
 * Antes: `python run.py`. URL: HELPDESK_URL (default http://127.0.0.1:8787).
 * macOS: Concede **Accesibilidad** a `Electron.app` (el que ejecuta `npm start`, suele estar en
 * `node_modules/electron/dist/Electron.app`) para que dejen de salir avisos y funcionen clic/movimiento.
 */
const { app, BrowserWindow, ipcMain, screen, shell } = require("electron");
const path = require("path");

const base =
  process.env.HELPDESK_URL ||
  process.env.HELPDESK_BASE ||
  "http://127.0.0.1:8787";

function startUrl() {
  const root = base.replace(/\/$/, "");
  const tid = (process.env.HELPDESK_THREAD_ID || "").trim();

  if (process.env.HELPDESK_ELECTRON_PAGE === "widget") {
    let u =
      tid.length >= 8
        ? `${root}/widget?thread=${encodeURIComponent(tid)}`
        : `${root}/widget`;
    const sep = u.includes("?") ? "&" : "?";
    return `${u}${sep}electron_float=1`;
  }

  let u = `${root}/?electron_app=1`;
  if (tid.length >= 8) {
    u += `&thread=${encodeURIComponent(tid)}`;
  }
  return u;
}

function sleep(ms) {
  return new Promise((resolve) =>
    setTimeout(resolve, Math.min(Math.max(ms, 0), 15000))
  );
}

function createWindow() {
  const { workArea } = screen.getPrimaryDisplay();
  const isWidget = process.env.HELPDESK_ELECTRON_PAGE === "widget";
  const alwaysOnTop = isWidget
    ? true
    : process.env.HELPDESK_ALWAYS_ON_TOP === "1";

  let winW;
  let winH;
  let winX;
  let winY;

  if (isWidget) {
    winW = 300;
    winH = Math.min(560, Math.max(360, workArea.height - 32));
    winX = workArea.x + workArea.width - winW - 6;
    winY = workArea.y + 10;
  } else {
    winW = Math.min(1240, Math.max(900, workArea.width - 40));
    winH = Math.min(880, Math.max(620, workArea.height - 40));
    winX = workArea.x + Math.round((workArea.width - winW) / 2);
    winY = workArea.y + Math.round((workArea.height - winH) / 2);
  }

  const win = new BrowserWindow({
    width: winW,
    height: winH,
    x: winX,
    y: winY,
    minWidth: isWidget ? 260 : 800,
    minHeight: isWidget ? 280 : 520,
    frame: !isWidget,
    alwaysOnTop: alwaysOnTop,
    show: false,
    backgroundColor: "#f4f6f9",
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: false,
    },
  });

  if (process.platform === "darwin") {
    win.setVisibleOnAllWorkspaces(true, { visibleOnFullScreen: true });
  }

  win.once("ready-to-show", () => win.show());
  win.loadURL(startUrl());

  win.webContents.setWindowOpenHandler(({ url }) => {
    shell.openExternal(url);
    return { action: "deny" };
  });
}

ipcMain.handle("desktop:screen", () => {
  const d = screen.getPrimaryDisplay();
  return { width: d.bounds.width, height: d.bounds.height, scaleFactor: d.scaleFactor };
});

ipcMain.handle("desktop:exec", async (_e, action) => {
  if (!action || typeof action !== "object") return "Acción inválida";
  const t = action.type;
  if (!["move", "click", "wait", "type", "hotkey"].includes(t)) {
    return "Tipo no permitido";
  }

  let nut;
  try {
    nut = require("@nut-tree-fork/nut-js");
  } catch (e) {
    return "Instala dependencias en electron/: npm install";
  }

  const { mouse, Button, Point, keyboard, Key, clipboard } = nut;
  const d = screen.getPrimaryDisplay();
  const w = d.bounds.width;
  const h = d.bounds.height;

  function keyByName(name) {
    const k = Key[name];
    if (k === undefined) return null;
    return k;
  }

  try {
    if (t === "hotkey") {
      const names = Array.isArray(action.keys) ? action.keys : [];
      const resolved = [];
      for (const n of names) {
        const k = keyByName(String(n));
        if (k === null) return "Tecla desconocida: " + n;
        resolved.push(k);
      }
      if (resolved.length === 0) return "hotkey sin teclas";
      // Chord: pressKey mantiene modificadores; type() pulsa teclas una tras otra (incorrecto para ⌘+Space).
      await keyboard.pressKey(...resolved);
      await keyboard.releaseKey(...resolved);
    } else if (t === "move") {
      const x = Math.round(Number(action.x) * w);
      const y = Math.round(Number(action.y) * h);
      await mouse.setPosition(new Point(x, y));
    } else if (t === "click") {
      const btn = action.button === "right" ? Button.RIGHT : Button.LEFT;
      await mouse.click(btn);
    } else if (t === "wait") {
      await sleep(Number(action.delayMs) || 0);
      return null;
    } else if (t === "type") {
      let txt = String(action.text || "");
      txt = txt.replace(/\\n/g, "\n");
      const hasNonAscii = [...txt].some((c) => c.charCodeAt(0) > 127);
      if (hasNonAscii) {
        await clipboard.setContent(txt);
        if (process.platform === "darwin") {
          await keyboard.pressKey(Key.LeftCmd, Key.V);
          await keyboard.releaseKey(Key.LeftCmd, Key.V);
        } else {
          await keyboard.pressKey(Key.LeftControl, Key.V);
          await keyboard.releaseKey(Key.LeftControl, Key.V);
        }
      } else {
        await keyboard.type(txt);
      }
    }
    if (t !== "wait") {
      await sleep(Math.min(Number(action.delayMs) || 0, 5000));
    }
    return null;
  } catch (e) {
    return e && e.message ? e.message : String(e);
  }
});

app.whenReady().then(createWindow);

app.on("window-all-closed", () => {
  app.quit();
});

app.on("activate", () => {
  if (BrowserWindow.getAllWindows().length === 0) createWindow();
});
