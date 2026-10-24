// Confirm step for destructive shared actions (e.g. Reset demo).
document.querySelectorAll("form[data-confirm]").forEach(function (form) {
  form.addEventListener("submit", function (e) {
    if (!window.confirm(form.dataset.confirm)) { e.preventDefault(); e.stopImmediatePropagation(); }
  });
});

// Page-level busy state: one POST at a time (every run pays for a real sandbox order/capture).
function setBusy(on) {
  if (on) {
    document.body.setAttribute("data-busy", "");
    document.body.setAttribute("aria-busy", "true");
  } else {
    document.body.removeAttribute("data-busy");
    document.body.removeAttribute("aria-busy");
  }
}
document.querySelectorAll("form.js-busy").forEach(function (form) {
  form.addEventListener("submit", function (e) {
    if (document.body.hasAttribute("data-busy")) return; // a submit listener further down blocks it
    // Disabling the buttons below also drops the clicked button's name=value from the form data (the HTML spec skips
    // disabled fields), so a form whose buttons carry the choice (e.g. the live agent's goal) would post without it.
    // Carry the submitter's value over in a hidden field first.
    var s = e.submitter;
    if (s && s.name && !form.querySelector("input[type=hidden][data-submitter]")) {
      var h = document.createElement("input");
      h.type = "hidden"; h.name = s.name; h.value = s.value; h.setAttribute("data-submitter", "");
      form.appendChild(h);
    }
    form.classList.add("busy-now");
    setBusy(true);
    form.querySelectorAll("button[type=submit], button:not([type])").forEach(function (b) {
      b.disabled = true;
      b.dataset.label = b.textContent;
      b.textContent = "Working…";
    });
  });
});
// Keyboard submits skip pointer-events, so block ANY submit while busy at the capture phase
// (the first POST is already navigating; a second one can only be a duplicate).
document.addEventListener("submit", function (e) {
  if (document.body.hasAttribute("data-busy")) e.preventDefault();
}, true);
// Back/forward from the bfcache restores the frozen page: unfreeze the buttons and the label.
window.addEventListener("pageshow", function (e) {
  if (!e.persisted) return;
  setBusy(false);
  document.querySelectorAll("form.js-busy button[data-label]").forEach(function (b) {
    b.disabled = false;
    b.textContent = b.dataset.label;
    delete b.dataset.label;
  });
  document.querySelectorAll("form.js-busy.busy-now").forEach(function (f) { f.classList.remove("busy-now"); });
  document.querySelectorAll("form.js-busy input[data-submitter]").forEach(function (h) { h.remove(); });
  if (window.__tradeosRestore) window.__tradeosRestore();
});

// Free-text box: presets fill the box (editable), live character count, and a draft that survives
// the reloads every action triggers (the server only echoes a draft on the too-long 422).
(function () {
  var box = document.getElementById("message");
  if (!box) return;
  var late = document.getElementById("late");
  var preset = document.getElementById("preset");
  var count = document.getElementById("count");
  var form = document.getElementById("free-form");
  var KEY = "tradeos.free-draft", SENT = "tradeos.free-sent";
  function save() {
    try {
      localStorage.setItem(KEY, JSON.stringify({ m: box.value, late: late.checked, preset: preset.value }));
    } catch (e) { /* private mode / quota: the draft then simply does not survive reloads */ }
  }
  function update() { if (count) count.textContent = box.value.length; }
  function restore() {
    // A server-provided draft (the 422 too-long page) always wins; a successful submit clears the
    // draft, anything else (reload, back/forward) brings it back.
    var sent = false;
    try { sent = sessionStorage.getItem(SENT) === "1"; sessionStorage.removeItem(SENT); } catch (e) {}
    if (box.value || sent) { update(); return; }
    var saved = null;
    try { saved = JSON.parse(localStorage.getItem(KEY) || "null"); } catch (e) { saved = null; }
    if (!saved || !saved.m) return;
    var max = parseInt(box.getAttribute("maxlength") || "0", 10);
    box.value = max > 0 ? saved.m.slice(0, max) : saved.m;
    late.checked = !!saved.late;
    preset.value = saved.preset || "";
    document.querySelectorAll(".chip-btn").forEach(function (c) {
      c.classList.toggle("on", c.dataset.message === box.value && c.dataset.preset === (saved.preset || ""));
    });
  }
  document.querySelectorAll(".chip-btn").forEach(function (chip) {
    chip.addEventListener("click", function () {
      box.value = chip.dataset.message;
      late.checked = chip.dataset.late === "1";
      preset.value = chip.dataset.preset;
      document.querySelectorAll(".chip-btn").forEach(function (c) { c.classList.remove("on"); });
      chip.classList.add("on");
      save();
      update();
      box.focus();
    });
  });
  box.addEventListener("input", function () { save(); update(); });
  late.addEventListener("change", save);
  restore();
  update();
  if (form) {
    form.addEventListener("submit", function () {
      try { sessionStorage.setItem(SENT, "1"); } catch (e) { /* same as above */ }
    });
  }
  window.__tradeosRestore = function () { restore(); update(); }; // pageshow (bfcache) hook above
})();

// After a refund, PayPal's signed webhook arrives a few seconds later: poll with backoff, reload
// once it shows up, and never fail silently — the sandbox commonly drops or delays webhooks.
(function () {
  var card = document.querySelector("[data-await-webhook]");
  if (!card || !window.fetch) return;
  var id = card.getAttribute("data-await-webhook");
  var MAX_TRIES = 40, MAX_DELAY = 15000;
  var tries = 0, fails = 0, delay = 4000, timer;
  var note = document.getElementById("webhook-note");
  function say(msg) { if (note) { note.hidden = false; note.textContent = msg; } }
  function stop() { clearTimeout(timer); }
  function tick() {
    tries += 1;
    fetch("/api/cases/" + encodeURIComponent(id), { cache: "no-store" }).then(function (r) {
      if (r.status === 404) { stop(); say("The case API answers 404 — the demo was probably reset. Reload the dashboard."); return null; }
      if (!r.ok) throw new Error("HTTP " + r.status);
      return r.json();
    }).then(function (d) {
      if (d && d.case && d.case.webhook_status) {
        stop();
        if (!document.body.hasAttribute("data-busy")) location.reload(); // never cut a POST in flight
        return;
      }
      fails = 0;
      if (tries >= MAX_TRIES) {
        stop();
        say("No signed webhook after " + tries + " checks (~" + Math.round(tries * 6 / 60) + " min) — common in the " +
            "sandbox. The refund is still COMPLETED at PayPal: press “Check against PayPal” below to confirm.");
        return;
      }
      delay = Math.min(Math.round(delay * 1.5), MAX_DELAY);
      timer = setTimeout(tick, delay);
    }).catch(function () {
      fails += 1;
      if (fails === 3) say("The API is unreachable (" + fails + " checks in a row) — still retrying…");
      if (tries >= MAX_TRIES) { stop(); say("Stopped waiting: repeated errors reaching the API. Use “Check against PayPal”."); return; }
      delay = Math.min(Math.round(delay * 1.5), MAX_DELAY);
      timer = setTimeout(tick, delay);
    });
  }
  timer = setTimeout(tick, delay);
})();

// Print / save as PDF buttons (no inline handlers: the CSP is script-src 'self').
document.querySelectorAll("[data-print]").forEach(function (b) {
  b.addEventListener("click", function () { window.print(); });
});

// Agent run page (a live model or the scripted scenes): poll the run and append each step as it happens. The
// server builds every sentence (status_text, case_link, ...). Everything is set with textContent (never innerHTML),
// so a model that outputs markup cannot inject it.
(function () {
  var page = document.querySelector("[data-agent-run]");
  if (!page || !window.fetch || page.getAttribute("data-status") !== "running") return;
  var id = page.getAttribute("data-agent-run");
  var list = document.getElementById("run-steps"), empty = document.getElementById("run-empty");
  var status = document.getElementById("run-status"), finalBox = document.getElementById("run-final");
  var shown = list.children.length, fails = 0, ticks = 0, MAX_TICKS = 150;

  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text !== undefined) n.textContent = text;
    return n;
  }
  function stepItem(s) {
    var li = el("li"), r = s.result || {};
    if (s.scene) { li.appendChild(el("span", "muted", s.scene + ":")); li.appendChild(document.createTextNode(" ")); }
    li.appendChild(el("code", "", s.tool || ""));
    if (s.args) { li.appendChild(document.createTextNode(" ")); li.appendChild(el("span", "muted", JSON.stringify(s.args))); }
    li.appendChild(document.createTextNode(" → "));
    if (r.error) { li.appendChild(el("span", "bad-text", r.error)); return li; }
    var parts = [String(r.status || "").replace(/_/g, " ")];
    if (r.refund_api_calls !== undefined) parts.push("refund calls: " + r.refund_api_calls);
    if (r.note) parts.push(r.note);
    li.appendChild(document.createTextNode(parts.join(" · ")));
    return li;
  }
  function setStatus(chipClass, chipText, text) {
    status.textContent = "";
    status.appendChild(el("span", "chip " + chipClass, chipText));
    status.appendChild(document.createTextNode(" " + text));
  }
  function render(run) {
    for (; shown < run.steps.length; shown++) list.appendChild(stepItem(run.steps[shown]));
    if (empty) empty.hidden = run.steps.length > 0;
    if (run.status === "running") {
      setStatus("warn", "Running", run.status_text);
      return false;
    }
    if (run.status === "failed") setStatus("bad", "Failed", run.status_text);
    else setStatus("ok", "Finished", run.status_text);
    document.getElementById("run-report-label").textContent = run.report_label + ":";
    document.getElementById("run-report").textContent = run.final_report || "—";
    var outcome = document.getElementById("run-outcome");
    outcome.textContent = "";
    if (run.case_link && /^\/(\?case=[\w-]+#[\w-]+|inbox)$/.test(run.case_link.href)) {  // only links into this app
      var a = el("a", "btn small", run.case_link.text);
      a.id = "run-case";
      a.href = run.case_link.href;
      outcome.appendChild(a);
    } else {
      outcome.textContent = run.no_case_text;
    }
    finalBox.hidden = false;
    page.setAttribute("data-status", run.status);
    return true;
  }
  function tick() {
    ticks += 1;
    fetch("/api/agent-runs/" + encodeURIComponent(id), { cache: "no-store" }).then(function (r) {
      if (r.status === 404) throw new Error("gone");
      if (!r.ok) throw new Error("HTTP " + r.status);
      return r.json();
    }).then(function (run) {
      fails = 0;
      if (!render(run) && ticks < MAX_TICKS) setTimeout(tick, 1500);
    }).catch(function (e) {
      fails += 1;
      if (e.message === "gone") { setStatus("bad", "Gone", "this run is no longer known here (the demo restarted?). Reload the dashboard."); return; }
      if (fails >= 3) setStatus("warn", "Retrying", "the server is not answering (" + fails + " tries)…");
      if (ticks < MAX_TICKS) setTimeout(tick, 3000);
    });
  }
  setTimeout(tick, 800);
})();

// Returns inbox: upgrade the server-rendered table to a sortable, filterable AG Grid. If the grid script did not
// load (or fetch fails), the table stays, so the page always works. Cells are built from DOM nodes with
// textContent, never HTML strings: buyer names and agent names come from outside.
(function () {
  var host = document.getElementById("inbox-grid");
  if (!host || !window.agGrid || !window.fetch) return;
  var table = document.getElementById("inbox-table"), tools = document.getElementById("inbox-tools");
  var search = document.getElementById("inbox-search"), mode = "all";

  function node(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text !== undefined && text !== null) n.textContent = String(text);
    return n;
  }
  function caseHref(id) { return "/?case=" + encodeURIComponent(id); }
  var MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  function when(iso) {  // "24 Oct 11:13" in UTC: short enough for the column, the same for every viewer
    var d = new Date(iso);
    if (isNaN(d)) return iso;
    var hh = ("0" + d.getUTCHours()).slice(-2), mm = ("0" + d.getUTCMinutes()).slice(-2);
    return d.getUTCDate() + " " + MONTHS[d.getUTCMonth()] + " " + hh + ":" + mm;
  }
  var narrow = window.matchMedia && window.matchMedia("(max-width: 640px)").matches;
  function statusText(v) { return String(v || "").replace(/_/g, " "); }
  var columns = [
    { headerName: "Received", headerTooltip: "When the request arrived (UTC)", field: "received", sort: "desc", width: 134, hide: narrow, tooltipField: "received",
      valueFormatter: function (p) { return when(p.value); },
      cellRenderer: function (p) { var a = node("a", "", when(p.value)); a.href = caseHref(p.data.id); return a; } },
    { headerName: "Needs", field: "bucket_label", width: 116,
      cellRenderer: function (p) { return node("span", "cell-chip " + p.data.bucket, p.value); } },
    { headerName: "From", field: "requested_by", flex: 1.3, minWidth: 200, tooltipField: "requested_by",
      getQuickFilterText: function (p) { return p.data.channel + " " + p.value + " " + (p.data.label || ""); },
      cellRenderer: function (p) {
        var wrap = node("span", "ell");
        if (p.data.from_agent) {
          wrap.appendChild(node("span", "cell-chip agent", "AI agent"));
          wrap.appendChild(node("span", "", p.value));
          wrap.appendChild(node("span", "cell-sub" + (p.data.verified ? " verified" : ""),
                                p.data.verified ? "verified" : "self-declared"));
        } else {
          wrap.appendChild(node("span", "", "Customer message"));
        }
        return wrap;
      } },
    { headerName: "Buyer", field: "buyer", flex: 1, minWidth: 110, tooltipField: "buyer", hide: narrow },
    { headerName: "Request", field: "request", width: 106, tooltipField: "request", hide: narrow },
    { headerName: "Amount", field: "amount", width: 108, type: "rightAligned" },
    { headerName: "Next step", field: "next_step", flex: 2, minWidth: 240,
      cellRenderer: function (p) { return node("div", "clamp2", p.value); },
      getQuickFilterText: function (p) { return statusText(p.data.status) + " " + p.value + " " + (p.data.why || ""); },
      tooltipValueGetter: function (p) { return statusText(p.data.status) + (p.data.why ? " · " + p.data.why : ""); } },
    { headerName: "Refunds", headerTooltip: "PayPal Refund API calls made for this request", field: "refund_api_calls",
      width: 102, type: "numericColumn", hide: narrow },
    { headerName: "Audit", headerTooltip: "The case's hash-chained audit trail verifies", field: "chain_ok", width: 84, hide: narrow,
      cellRenderer: function (p) { return p.value ? node("span", "", "intact") : node("span", "cell-bad", "BROKEN"); } }
  ];

  function setMode(next) {
    mode = next;
    Array.prototype.forEach.call(document.querySelectorAll("[data-inbox-filter]"), function (b) {
      b.setAttribute("aria-pressed", b.getAttribute("data-inbox-filter") === mode ? "true" : "false");
    });
  }

  fetch("/api/inbox", { cache: "no-store" }).then(function (r) {
    if (!r.ok) throw new Error("HTTP " + r.status);
    return r.json();
  }).then(function (data) {
    var api = window.agGrid.createGrid(host, {
      theme: "legacy",
      rowData: data.rows,
      columnDefs: columns,
      defaultColDef: { sortable: true, resizable: true, suppressHeaderMenuButton: true },  // search + buttons filter
      getRowId: function (p) { return p.data.id; },
      domLayout: "autoHeight",
      rowHeight: 58,
      pagination: true, paginationPageSize: 20, paginationPageSizeSelector: false,
      tooltipShowDelay: 300,
      isExternalFilterPresent: function () { return mode !== "all"; },
      doesExternalFilterPass: function (n) {
        return mode === "needs_you" ? n.data.bucket === "needs_you" : mode === "agents" ? n.data.from_agent : true;
      },
      onRowClicked: function (e) {
        if (e.event && e.event.target && e.event.target.closest("a")) return;  // the link handles itself
        window.location.href = caseHref(e.data.id);
      },
      onCellKeyDown: function (e) {
        if (e.event && e.event.key === "Enter") window.location.href = caseHref(e.data.id);
      }
    });
    Array.prototype.forEach.call(document.querySelectorAll("[data-inbox-filter]"), function (b) {
      b.addEventListener("click", function () { setMode(b.getAttribute("data-inbox-filter")); api.onFilterChanged(); });
    });
    if (search) search.addEventListener("input", function () { api.setGridOption("quickFilterText", search.value); });
    if (data.summary && data.summary.needs_you > 0) { setMode("needs_you"); api.onFilterChanged(); }
    host.hidden = false;
    if (tools) tools.hidden = false;
    if (table) table.hidden = true;
  }).catch(function () { /* keep the server-rendered table */ });
})();
