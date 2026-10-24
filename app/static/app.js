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

// Live AI agent run page: poll the run and append each step as the model takes it. Everything the model wrote is
// set with textContent (never innerHTML), so a model that outputs markup cannot inject it.
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
      setStatus("warn", "Running", run.phase === "thinking" ? "the model is deciding (call " + run.model_calls + " of at most 6)…"
                : run.phase === "step" ? "tool call done; the model is reading the result…" : "starting…");
      return false;
    }
    if (run.status === "failed") {
      setStatus("bad", "Failed", "the run stopped with an internal error (" + run.error + "). Nothing was approved or refunded.");
    } else {
      setStatus("ok", "Finished", run.stop_reason + " · " + run.model_calls + " model calls · " + run.tokens + " tokens · " + run.seconds + " s");
    }
    document.getElementById("run-report").textContent = run.final_report || "—";
    var outcome = document.getElementById("run-outcome");
    outcome.textContent = "";
    if (run.case_id) {
      var a = el("a", "btn small", "Open the order and its audit trail");
      a.id = "run-case";
      a.href = "/?case=" + encodeURIComponent(run.case_id) + "#live-run";
      outcome.appendChild(a);
    } else {
      outcome.textContent = "The model placed no order, so nothing was recorded on a case and nothing was refunded.";
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
