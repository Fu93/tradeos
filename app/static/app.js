// Confirm step for destructive shared actions (e.g. Reset demo).
document.querySelectorAll("form[data-confirm]").forEach(function (form) {
  form.addEventListener("submit", function (e) {
    if (!window.confirm(form.dataset.confirm)) { e.preventDefault(); e.stopImmediatePropagation(); }
  });
});

// Minimal progressive enhancement: prevent double submits and show progress
// while TradeOS talks to PayPal (the refund itself is also idempotent server-side).
document.querySelectorAll("form.js-busy").forEach(function (form) {
  form.addEventListener("submit", function () {
    form.querySelectorAll("button[type=submit], button:not([type])").forEach(function (b) {
      b.disabled = true;
      b.dataset.label = b.textContent;
      b.textContent = "Working… (PayPal Sandbox)";
    });
  });
});

// Free-text box: presets fill the box (editable), live character count.
(function () {
  var box = document.getElementById("message");
  if (!box) return;
  var late = document.getElementById("late");
  var preset = document.getElementById("preset");
  var count = document.getElementById("count");
  function update() { if (count) count.textContent = box.value.length; }
  document.querySelectorAll(".chip-btn").forEach(function (chip) {
    chip.addEventListener("click", function () {
      box.value = chip.dataset.message;
      late.checked = chip.dataset.late === "1";
      preset.value = chip.dataset.preset;
      document.querySelectorAll(".chip-btn").forEach(function (c) { c.classList.remove("on"); });
      chip.classList.add("on");
      update();
      box.focus();
    });
  });
  box.addEventListener("input", update);
  update();
})();

// After a refund, PayPal's signed webhook arrives a few seconds later: poll briefly, then reload once.
(function () {
  var card = document.querySelector("[data-await-webhook]");
  if (!card || !window.fetch) return;
  var id = card.getAttribute("data-await-webhook"), tries = 0;
  var timer = setInterval(function () {
    if (++tries > 30) return clearInterval(timer);
    fetch("/api/cases/" + encodeURIComponent(id)).then(function (r) { return r.json(); }).then(function (d) {
      if (d.case && d.case.webhook_status) { clearInterval(timer); location.reload(); }
    }).catch(function () {});
  }, 4000);
})();
