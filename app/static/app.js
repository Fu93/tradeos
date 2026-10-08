// Minimal progressive enhancement: prevent double submits and show progress
// while TradeOS talks to PayPal (the refund itself is also idempotent server-side).
document.querySelectorAll("form.js-busy").forEach(function (form) {
  form.addEventListener("submit", function () {
    form.querySelectorAll("button").forEach(function (b) {
      b.disabled = true;
      b.dataset.label = b.textContent;
      b.textContent = "Working…";
    });
  });
});
