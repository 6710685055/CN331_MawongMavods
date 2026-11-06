// UC14: ask once more before a destructive decision. The prompt comes from data-confirm-message;
// the server still requires the confirm checkbox, so this is only a UX safeguard.
(function () {
  "use strict";
  document.addEventListener("DOMContentLoaded", function () {
    document.querySelectorAll("form[data-confirm-message]").forEach(function (form) {
      form.addEventListener("submit", function (event) {
        if (!window.confirm(form.dataset.confirmMessage)) event.preventDefault();
      });
    });
  });
})();
