const logEl = document.getElementById("log");
const planEl = document.getElementById("plan");
const rationaleEl = document.getElementById("rationale");
const btnPlan = document.getElementById("btnPlan");
const btnRunAll = document.getElementById("btnRunAll");
const yoloEl = document.getElementById("yolo");

let lastActions = [];

function log(msg) {
  logEl.textContent += (logEl.textContent ? "\n" : "") + new Date().toISOString().slice(11, 19) + " " + msg;
  logEl.scrollTop = logEl.scrollHeight;
}

function sleep(ms) {
  return new Promise((r) => setTimeout(r, ms));
}

btnPlan.addEventListener("click", async () => {
  const goal = document.getElementById("goal").value.trim();
  if (!goal) return;
  btnPlan.disabled = true;
  planEl.innerHTML = "";
  rationaleEl.textContent = "";
  lastActions = [];
  btnRunAll.disabled = true;
  log("Solicitando plan…");
  try {
    const data = await window.nativeDesk.fetchPlan(goal);
    rationaleEl.textContent = data.rationale || "";
    lastActions = data.actions || [];
    if (!lastActions.length) {
      log("Plan vacío (el modelo rechazó acciones o no hubo JSON válido).");
      return;
    }
    lastActions.forEach((a, i) => {
      const div = document.createElement("div");
      div.className = "step";
      div.innerHTML = `<strong>Paso ${i + 1}</strong> — <code>${JSON.stringify(a)}</code>`;
      const b = document.createElement("button");
      b.textContent = "Ejecutar este paso";
      b.addEventListener("click", async () => {
        b.disabled = true;
        await execOne(a);
        b.disabled = false;
      });
      div.appendChild(b);
      planEl.appendChild(div);
    });
    btnRunAll.disabled = false;
    log("Plan recibido: " + lastActions.length + " paso(s).");
  } catch (e) {
    log("Error plan: " + (e && e.message ? e.message : String(e)));
  } finally {
    btnPlan.disabled = false;
  }
});

async function execOne(action) {
  log("Ejecutando: " + JSON.stringify(action));
  const err = await window.nativeDesk.runAction(action);
  if (err) log("Fallo: " + err);
  else log("OK");
}

btnRunAll.addEventListener("click", async () => {
  const yolo = yoloEl.checked;
  if (!lastActions.length) return;
  if (yolo) {
    const ok = confirm(
      "YOLO: se ejecutarán todos los pasos seguidos con pausa corta, sin pedir confirmación en cada uno. ¿Continuar?"
    );
    if (!ok) return;
  } else {
    const ok = confirm("Se ejecutarán todos los pasos; se pedirá confirmación antes de cada uno. ¿Continuar?");
    if (!ok) return;
  }
  btnRunAll.disabled = true;
  for (let i = 0; i < lastActions.length; i++) {
    const a = lastActions[i];
    if (!yolo) {
      const go = confirm("Ejecutar paso " + (i + 1) + "?\n" + JSON.stringify(a));
      if (!go) {
        log("Cancelado en paso " + (i + 1));
        break;
      }
    }
    await execOne(a);
    await sleep(yolo ? 1200 : 400);
  }
  btnRunAll.disabled = false;
});
