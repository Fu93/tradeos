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
  form.addEventListener("submit", function () {
    if (document.body.hasAttribute("data-busy")) return; // a submit listener further down blocks it
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
