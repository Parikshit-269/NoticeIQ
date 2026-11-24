"use strict";
const $ = (sel, root = document) => root.querySelector(sel);
const view = $("#view");
const CAT = {
  deadline: "Deadlines", eligibility: "Eligibility", fee: "Fees & amounts", document: "Required documents", date: "Other dates",
};

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}
function toast(msg, isError = false) {
  const t = $("#toast");
  t.textContent = msg; t.className = "toast show" + (isError ? " error" : "");
  clearTimeout(toast._t); toast._t = setTimeout(() => (t.className = "toast"), 3500);
}
async function api(path, opts = {}) {
  const res = await fetch("/api" + path, opts);
  let body = null;
  try { body = await res.json(); } catch { /* non-JSON */ }
  if (!res.ok) {
    const d = body && body.detail;
    throw new Error(typeof d === "string" ? d : Array.isArray(d) ? d.map(x => x.msg).join("; ") : `Request failed (${res.status})`);
  }
  return body;
}
function daysLeft(iso) {
  if (!iso) return null;
  const today = new Date(); today.setHours(0, 0, 0, 0);
  return Math.round((new Date(iso + "T00:00:00") - today) / 86400000);
}
function dueHtml(iso) {
  if (!iso) return '<span class="due">—</span>';
  const d = daysLeft(iso);
  const fmt = new Date(iso + "T00:00:00").toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });
  const cls = d < 0 ? "overdue" : d <= 7 ? "soon" : "";
  const rel = d < 0 ? `${-d} day(s) ago` : d === 0 ? "today" : `in ${d} day(s)`;
  return `<span class="due ${cls}">${fmt} · ${rel}</span>`;
}

/* ---------- Upload ---------- */
function renderUpload() {
  view.innerHTML = `
    <h1>Analyse a notice</h1>
    <p class="sub">Upload a college circular or scholarship notice (PDF). NoticeIQ extracts deadlines, eligibility, fees and
      required documents, each linked to the page and line it came from.</p>
    <div class="card">
      <label class="dropzone" id="drop">
        <strong>Drop a PDF here or click to choose</strong>
        <span class="sub">PDF only · up to 10 MB · text-based PDFs (scanned pages are reported, not OCR'd)</span>
        <input type="file" id="fileInput" accept="application/pdf,.pdf">
      </label>
      <div class="progress" id="prog"><div></div></div>
      <div id="uploadMsg" style="margin-top:14px"></div>
    </div>`;
  const drop = $("#drop"), input = $("#fileInput");
  input.addEventListener("change", () => input.files[0] && upload(input.files[0]));
  ["dragenter", "dragover"].forEach(ev => drop.addEventListener(ev, e => { e.preventDefault(); drop.classList.add("over"); }));
  ["dragleave", "drop"].forEach(ev => drop.addEventListener(ev, e => { e.preventDefault(); drop.classList.remove("over"); }));
  drop.addEventListener("drop", e => e.dataTransfer.files[0] && upload(e.dataTransfer.files[0]));
}

function upload(file) {
  const msg = $("#uploadMsg"), prog = $("#prog"), bar = $("#prog > div");
  if (!file.name.toLowerCase().endsWith(".pdf")) { msg.innerHTML = `<div class="alert error">Please choose a .pdf file.</div>`; return; }
  if (file.size > 10 * 1024 * 1024) { msg.innerHTML = `<div class="alert error">File is larger than 10 MB.</div>`; return; }
  const fd = new FormData(); fd.append("file", file);
  const xhr = new XMLHttpRequest();
  xhr.open("POST", "/api/documents");
  prog.style.display = "block"; bar.style.width = "0";
  msg.innerHTML = `<div class="empty">Uploading ${esc(file.name)}…</div>`;
  xhr.upload.onprogress = e => { if (e.lengthComputable) bar.style.width = (e.loaded / e.total * 100) + "%"; };
  xhr.onload = () => {
    prog.style.display = "none";
    let body = {}; try { body = JSON.parse(xhr.responseText); } catch { /* ignore */ }
    if (xhr.status >= 200 && xhr.status < 300) {
      toast(body.message || "Analysis complete.");
      location.hash = `#/doc/${body.id}`;
    } else {
      msg.innerHTML = `<div class="alert error">${esc(body.detail || "Upload failed.")}</div>`;
    }
  };
  xhr.onerror = () => { prog.style.display = "none"; msg.innerHTML = `<div class="alert error">Network error — is the server running?</div>`; };
  xhr.send(fd);
}

/* ---------- Documents list ---------- */
async function renderDocuments() {
  view.innerHTML = `<h1>Saved documents</h1><p class="sub">Every upload and its analysis is stored locally in SQLite.</p><div id="list" class="card">Loading…</div>`;
  const docs = await api("/documents");
  const list = $("#list");
  if (!docs.length) { list.innerHTML = `<p class="empty">No documents yet. <a href="#/upload">Upload a notice</a> to get started.</p>`; return; }
  list.innerHTML = `<table><thead><tr><th>Title</th><th class="hide-sm">Pages</th><th>Facts</th><th>Tasks done</th><th>Next deadline</th><th></th></tr></thead><tbody>
    ${docs.map(d => `<tr>
      <td><a href="#/doc/${d.id}"><strong>${esc(d.title)}</strong></a><br><span class="empty">${esc(d.filename)}</span>
        ${d.ocr_pages.length ? `<br><span class="badge medium">OCR needed: p.${d.ocr_pages.join(", ")}</span>` : ""}</td>
      <td class="hide-sm">${d.page_count}</td><td>${d.fact_count}</td><td>${d.done_count}/${d.task_count}</td>
      <td>${dueHtml(d.next_due)}</td>
      <td><button class="btn danger" data-del="${d.id}">Delete</button></td></tr>`).join("")}
    </tbody></table>`;
  list.querySelectorAll("[data-del]").forEach(b => b.addEventListener("click", async () => {
    if (!confirm("Delete this document and its tasks?")) return;
    try { await api(`/documents/${b.dataset.del}`, { method: "DELETE" }); toast("Deleted."); renderDocuments(); }
    catch (e) { toast(e.message, true); }
  }));
}

/* ---------- Document detail ---------- */
async function renderDoc(id) {
  view.innerHTML = "Loading…";
  let doc;
  try { doc = await api(`/documents/${id}`); }
  catch (e) { view.innerHTML = `<div class="alert error">${esc(e.message)}</div><a href="#/documents">Back to documents</a>`; return; }
  const by = c => doc.facts.filter(f => f.category === c);
  const allScanned = doc.ocr_pages.length === doc.page_count;
  const factCard = cat => {
    const facts = by(cat);
    const sorted = cat === "deadline" ? facts.sort((a, b) => a.normalized.localeCompare(b.normalized)) : facts;
    return `<div class="card"><h2>${CAT[cat]} ${facts.length ? `<span class="badge low">${facts.length}</span>` : ""}</h2>
      ${facts.length ? sorted.map(f => `<div class="fact">
        <div class="val">${esc(f.value)}${f.label && cat !== "eligibility" && cat !== "document" ? ` <span style="font-weight:400">— ${esc(f.label)}</span>` : ""}</div>
        ${cat === "deadline" ? `<div>${dueHtml(f.normalized)}</div>` : ""}
        <div class="meta"><span class="badge ${f.confidence}">${f.confidence} confidence</span><span>Page ${f.page}</span>
          <button class="linklike" data-ev="${f.id}">View evidence</button></div>
        ${f.note ? `<div class="note">⚠ ${esc(f.note)}</div>` : ""}</div>`).join("")
        : `<p class="empty"><span class="badge missing">Not found</span> No ${CAT[cat].toLowerCase()} detected in this document's text.
           Check the original notice.</p>`}</div>`;
  };
  view.innerHTML = `
    <div class="row" style="justify-content:space-between;margin-bottom:8px">
      <div><h1 id="docTitle">${esc(doc.title)}</h1>
        <p class="sub" style="margin:0">${esc(doc.filename)} · ${doc.page_count} page(s) · saved ${new Date(doc.uploaded_at).toLocaleString()}</p></div>
      <div class="row">
        <button class="btn ghost" id="renameBtn">Rename</button>
        <a class="btn ghost" href="/api/documents/${doc.id}/export.json">Export JSON</a>
        <a class="btn ghost" href="/api/documents/${doc.id}/report.html?download=false" target="_blank" rel="noopener">View report</a>
        <a class="btn" href="/api/documents/${doc.id}/report.html">Download report</a>
      </div>
    </div>
    <div style="margin-top:18px">
    ${allScanned ? `<div class="alert error">This PDF has no selectable text — it appears to be scanned. OCR is required and is not included,
        so no facts could be extracted.</div>` :
      doc.ocr_pages.length ? `<div class="alert warn">Page(s) ${doc.ocr_pages.join(", ")} appear to be scanned images and were not read.</div>` : ""}
    ${doc.missing.length && !allScanned ? `<div class="alert warn">Not found in the text: ${doc.missing.map(m => CAT[m]).join(", ")}.
        NoticeIQ does not guess missing information.</div>` : ""}
    </div>
    <div class="grid">${factCard("deadline")}${factCard("fee")}</div>
    <div class="grid">${factCard("eligibility")}${factCard("document")}</div>
    ${by("date").length ? factCard("date") : ""}
    <div class="card"><h2>Action checklist</h2><div id="docTasks"></div></div>`;
  renderTaskTable($("#docTasks"), doc.tasks, false);
  view.querySelectorAll("[data-ev]").forEach(b => b.addEventListener("click", () => {
    showEvidence(doc, doc.facts.find(f => String(f.id) === b.dataset.ev));
  }));
  $("#renameBtn").addEventListener("click", async () => {
    const t = prompt("New title", doc.title);
    if (!t || !t.trim()) return;
    try { await api(`/documents/${doc.id}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ title: t.trim() }) });
      $("#docTitle").textContent = t.trim(); toast("Renamed."); } catch (e) { toast(e.message, true); }
  });
}

async function showEvidence(doc, fact) {
  const drawer = $("#evidence");
  $("#evTitle").textContent = `Evidence · page ${fact.page}`;
  $("#evBody").innerHTML = "Loading…";
  drawer.classList.add("open"); drawer.setAttribute("aria-hidden", "false");
  try {
    const page = await api(`/documents/${doc.id}/pages/${fact.page}`);
    const text = page.text;
    const needle = fact.evidence.replace(/…$/, "");
    // Page text keeps original spacing; match evidence loosely on whitespace.
    const pattern = new RegExp(needle.split(/\s+/).map(w => w.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("\\s+"));
    const m = pattern.exec(text);
    const body = m ? esc(text.slice(0, m.index)) + "<mark id='hit'>" + esc(m[0]) + "</mark>" + esc(text.slice(m.index + m[0].length)) : esc(text);
    $("#evBody").innerHTML = `
      <p><strong>${esc(CAT[fact.category])}:</strong> ${esc(fact.value)}</p>
      <p class="empty">Supporting text: “${esc(fact.evidence)}”</p>
      <div class="pagetext">${body || "<em>(no text on this page)</em>"}</div>`;
    const hit = $("#hit"); if (hit) hit.scrollIntoView({ block: "center" });
  } catch (e) { $("#evBody").innerHTML = `<div class="alert error">${esc(e.message)}</div>`; }
}
$("#evClose").addEventListener("click", () => { $("#evidence").classList.remove("open"); $("#evidence").setAttribute("aria-hidden", "true"); });

/* ---------- Tasks ---------- */
function renderTaskTable(root, tasks, showDoc) {
  if (!tasks.length) { root.innerHTML = `<p class="empty">No tasks were generated.</p>`; return; }
  root.innerHTML = `<table><thead><tr><th style="width:36px"></th><th>Task</th>${showDoc ? '<th class="hide-sm">Document</th>' : ""}<th>Due</th><th class="hide-sm">Page</th></tr></thead><tbody>
    ${tasks.map(t => `<tr class="task ${t.done ? "done" : ""}">
      <td><input type="checkbox" data-task="${t.id}" ${t.done ? "checked" : ""} aria-label="Mark done"></td>
      <td class="ttl">${esc(t.title)}</td>
      ${showDoc ? `<td class="hide-sm"><a href="#/doc/${t.document_id}">${esc(t.document_title)}</a></td>` : ""}
      <td>${dueHtml(t.due_date)}</td><td class="hide-sm">${t.source_page ?? ""}</td></tr>`).join("")}</tbody></table>`;
  root.querySelectorAll("[data-task]").forEach(cb => cb.addEventListener("change", async () => {
    try {
      await api(`/tasks/${cb.dataset.task}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ done: cb.checked }) });
      cb.closest("tr").classList.toggle("done", cb.checked);
    } catch (e) { cb.checked = !cb.checked; toast(e.message, true); }
  }));
}

async function renderTasks() {
  view.innerHTML = `<h1>Task dashboard</h1><p class="sub">All checklist items across your saved notices, sorted by due date.</p>
    <div class="filters" id="filters">
      ${["open", "upcoming", "overdue", "done", "all"].map((f, i) => `<button class="chip ${i === 0 ? "active" : ""}" data-f="${f}">${f[0].toUpperCase() + f.slice(1)}</button>`).join("")}
    </div><div class="card" id="taskList">Loading…</div>`;
  const tasks = await api("/tasks");
  const apply = f => {
    const sel = tasks.filter(t => {
      const d = daysLeft(t.due_date);
      return f === "all" ? true : f === "done" ? t.done : f === "open" ? !t.done
        : f === "upcoming" ? !t.done && d !== null && d >= 0 : !t.done && d !== null && d < 0;
    });
    renderTaskTable($("#taskList"), sel, true);
  };
  $("#filters").querySelectorAll(".chip").forEach(c => c.addEventListener("click", () => {
    $("#filters").querySelectorAll(".chip").forEach(x => x.classList.remove("active"));
    c.classList.add("active"); apply(c.dataset.f);
  }));
  apply("open");
}

/* ---------- Compare ---------- */
async function renderCompare() {
  const docs = await api("/documents");
  view.innerHTML = `<h1>Compare versions</h1><p class="sub">Pick an older and a newer version of a notice to see changed dates, fees and requirements.</p>
    ${docs.length < 2 ? `<div class="card"><p class="empty">You need at least two saved documents. <a href="#/upload">Upload another</a>.</p></div>` : `
    <div class="card row">
      <select id="ca" aria-label="Older version">${docs.map(d => `<option value="${d.id}">${esc(d.title)} (#${d.id})</option>`).join("")}</select>
      <span>→</span>
      <select id="cb" aria-label="Newer version">${docs.map((d, i) => `<option value="${d.id}" ${i === 0 ? "selected" : ""}>${esc(d.title)} (#${d.id})</option>`).join("")}</select>
      <button class="btn" id="cmpBtn">Compare</button>
    </div><div id="cmpOut"></div>`}`;
  if (docs.length < 2) return;
  $("#ca").value = docs[1].id;
  $("#cmpBtn").addEventListener("click", async () => {
    const out = $("#cmpOut");
    try {
      const r = await api(`/compare?a=${$("#ca").value}&b=${$("#cb").value}`);
      const fv = f => `${esc(f.value)}${f.category === "deadline" && f.label ? ` — ${esc(f.label)}` : ""} <span class="empty">(p.${f.page})</span>`;
      out.innerHTML = `<div class="grid">${["deadline", "fee", "eligibility", "document"].map(c => {
        const x = r.changes[c];
        const items = [
          ...x.changed.map(p => `<div class="diff-item">Changed: <span class="diff-del">${fv(p.before)}</span> → <span class="diff-add">${fv(p.after)}</span></div>`),
          ...x.added.map(f => `<div class="diff-item diff-add">+ ${fv(f)}</div>`),
          ...x.removed.map(f => `<div class="diff-item diff-del">− ${fv(f)}</div>`)];
        return `<div class="card"><h2>${CAT[c]}</h2>${items.join("") || `<p class="empty">No changes.</p>`}
          <p class="empty">${x.unchanged} unchanged</p></div>`;
      }).join("")}</div>`;
    } catch (e) { out.innerHTML = `<div class="alert error">${esc(e.message)}</div>`; }
  });
}

/* ---------- Router ---------- */
async function route() {
  const hash = location.hash || "#/upload";
  const [, name, arg] = hash.split("/");
  document.querySelectorAll("nav a").forEach(a => a.classList.toggle("active", a.dataset.route === (name === "doc" ? "documents" : name)));
  $("#nav").classList.remove("open");
  $("#evidence").classList.remove("open");
  try {
    if (name === "documents") await renderDocuments();
    else if (name === "doc" && arg) await renderDoc(arg);
    else if (name === "tasks") await renderTasks();
    else if (name === "compare") await renderCompare();
    else renderUpload();
  } catch (e) { view.innerHTML = `<div class="alert error">${esc(e.message)}</div>`; }
  window.scrollTo(0, 0);
}
$("#navToggle").addEventListener("click", () => {
  const nav = $("#nav"); nav.classList.toggle("open");
  $("#navToggle").setAttribute("aria-expanded", nav.classList.contains("open"));
});
window.addEventListener("hashchange", route);
route();
