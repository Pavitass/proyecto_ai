(function () {
  const panel = document.getElementById('automationPanel');
  const apThumb = document.getElementById('apThumb');
  const apStepInfo = document.getElementById('apStepInfo');
  const apHistory = document.getElementById('apHistory');
  const apStatus = document.getElementById('apStatus');
  const apAbort = document.getElementById('apAbort');
  const confirmModal = document.getElementById('apConfirmModal');
  const confirmImg = document.getElementById('apConfirmImg');
  const confirmAction = document.getElementById('apConfirmAction');
  const confirmApprove = document.getElementById('apConfirmApprove');
  const confirmCancel = document.getElementById('apConfirmCancel');
  let currentRun = null;
  let es = null;

  function show() { panel.hidden = false; }
  function hide() { panel.hidden = true; apHistory.innerHTML = ''; apStepInfo.textContent = ''; }

  async function postJSON(url, body) {
    return fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
  }

  function attachStream(runId) {
    currentRun = runId;
    show();
    apStatus.textContent = `Automatización · run ${runId}`;
    if (es) { es.close(); }
    es = new EventSource(`/api/desktop/loop/stream/${runId}`);
    es.addEventListener('step', (e) => {
      const d = JSON.parse(e.data);
      apThumb.src = 'data:image/png;base64,' + d.thumb_b64;
      apStepInfo.textContent = `Paso ${d.n}/${d.max} · ${d.summary} — ${d.reasoning}`;
      const li = document.createElement('li');
      li.textContent = `${d.n}. ${d.summary} — ${d.reasoning}`;
      apHistory.appendChild(li);
    });
    es.addEventListener('confirm_required', (e) => {
      const d = JSON.parse(e.data);
      confirmImg.src = 'data:image/png;base64,' + d.full_b64;
      confirmAction.textContent = `Paso ${d.n}: ${d.summary}\n${d.reasoning}\n\n${JSON.stringify(d.action, null, 2)}`;
      confirmModal.hidden = false;
      confirmApprove.onclick = () => { postJSON('/api/desktop/loop/confirm', { run_id: currentRun, approved: true }); confirmModal.hidden = true; };
      confirmCancel.onclick = () => { postJSON('/api/desktop/loop/confirm', { run_id: currentRun, approved: false }); confirmModal.hidden = true; };
    });
    es.addEventListener('done', () => { apStatus.textContent = 'Hecho.'; });
    es.addEventListener('fail', (e) => { const d = JSON.parse(e.data); apStatus.textContent = 'Fallo: ' + (d.reason || ''); });
    es.addEventListener('aborted', () => { apStatus.textContent = 'Abortado.'; });
    es.addEventListener('closed', () => { es.close(); setTimeout(hide, 4000); });
  }

  apAbort.addEventListener('click', () => {
    if (!currentRun) return;
    postJSON('/api/desktop/loop/abort', { run_id: currentRun });
  });

  window.helpdeskAttachAutomation = attachStream;

  // Auto-attach: observe chat messages for tool-result JSON containing run_id of ejecutar_tarea_escritorio.
  // The chat JS in index.html may already render tool results in some container. We do a generic
  // MutationObserver scan: whenever a node is added that mentions "run_id" and a 12-hex-char id, we attach.
  function _scanForRunId(node) {
    if (!node || !node.textContent) return;
    const m = node.textContent.match(/"run_id"\s*:\s*"([a-f0-9]{12})"/);
    if (m && m[1] !== currentRun) {
      try { attachStream(m[1]); } catch (e) { /* ignore */ }
    }
  }
  const obs = new MutationObserver((muts) => {
    for (const m of muts) {
      m.addedNodes.forEach(_scanForRunId);
    }
  });
  obs.observe(document.body, { childList: true, subtree: true });
})();
