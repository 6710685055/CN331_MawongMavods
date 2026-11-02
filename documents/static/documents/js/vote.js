// UC10: vote without reloading the page. Endpoint and values come from data-* attributes.
(function () {
  "use strict";

  function setActive(widget, myVote) {
    widget.querySelectorAll("[data-vote-button]").forEach(function (button) {
      var active = button.dataset.value === myVote;
      button.classList.toggle("active", active);
      button.setAttribute("aria-pressed", active ? "true" : "false");
    });
  }

  function bindWidget(widget) {
    var form = widget.querySelector("form");
    if (!form) return;

    form.addEventListener("submit", function (event) {
      if (!window.fetch || !event.submitter) return; // fall back to a normal form post
      event.preventDefault();

      var body = new FormData(form);
      body.set(event.submitter.name, event.submitter.value);
      var buttons = form.querySelectorAll("button");
      buttons.forEach(function (b) { b.disabled = true; });

      fetch(widget.dataset.voteUrl, {
        method: "POST",
        headers: {
          "Accept": "application/json",
          "X-CSRFToken": form.querySelector("[name=csrfmiddlewaretoken]").value,
        },
        body: body,
        credentials: "same-origin",
      })
        .then(function (response) {
          return response.json().then(function (data) { return { ok: response.ok, data: data }; });
        })
        .then(function (result) {
          if (!result.ok) {
            window.alert(result.data.error);
            return;
          }
          widget.querySelector("[data-vote-score]").textContent = result.data.score;
          setActive(widget, result.data.my_vote);
        })
        .catch(function () { form.submit(); })
        .finally(function () { buttons.forEach(function (b) { b.disabled = false; }); });
    });
  }

  function bindReportForm(form) {
    var detail = form.querySelector("textarea");
    if (!detail) return;
    form.addEventListener("change", function () {
      var checked = form.querySelector("input[type=radio]:checked");
      detail.required = Boolean(checked && checked.hasAttribute("data-requires-detail"));
    });
  }

  document.addEventListener("DOMContentLoaded", function () {
    document.querySelectorAll("[data-vote-widget]").forEach(bindWidget);
    document.querySelectorAll("[data-report-form]").forEach(bindReportForm);
  });
})();
