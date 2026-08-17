(function () {
  "use strict";

  function csrfHeader(event) {
    var token = document.querySelector('meta[name="csrf-token"]');
    if (token) event.detail.headers["X-CSRFToken"] = token.content;
  }

  function setupThemeToggle(root) {
    var button = root.querySelector("[data-theme-toggle]");
    if (!button || button.dataset.bound === "true") return;
    button.dataset.bound = "true";
    function updateLabel() {
      var dark = document.documentElement.dataset.theme === "dark";
      button.setAttribute("aria-label", dark ? "Cambiar a tema claro" : "Cambiar a tema oscuro");
      button.title = dark ? "Tema claro" : "Tema oscuro";
    }
    button.addEventListener("click", function () {
      var next = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
      document.documentElement.dataset.theme = next;
      try { window.localStorage.setItem("nbo-advisor-theme", next); } catch (error) {}
      updateLabel();
    });
    updateLabel();
  }

  function setupClientExamples(root) {
    root.querySelectorAll("[data-client-example]").forEach(function (link) {
      if (link.dataset.bound === "true") return;
      link.dataset.bound = "true";
      link.addEventListener("click", function () {
        var input = document.getElementById("cliente_id");
        if (input) input.value = link.dataset.clientExample;
      });
    });
  }

  function setupTabs(root) {
    root.querySelectorAll("[data-tabs]").forEach(function (tabs) {
      var buttons = Array.from(tabs.querySelectorAll('[role="tab"]'));
      function select(button) {
        buttons.forEach(function (item) {
          var selected = item === button;
          item.setAttribute("aria-selected", String(selected));
          item.tabIndex = selected ? 0 : -1;
          document.getElementById(item.getAttribute("aria-controls")).hidden = !selected;
        });
        button.focus();
      }
      buttons.forEach(function (button, index) {
        button.addEventListener("click", function () { select(button); });
        button.addEventListener("keydown", function (event) {
          var next = index;
          if (event.key === "ArrowRight") next = (index + 1) % buttons.length;
          else if (event.key === "ArrowLeft") next = (index - 1 + buttons.length) % buttons.length;
          else if (event.key === "Home") next = 0;
          else if (event.key === "End") next = buttons.length - 1;
          else return;
          event.preventDefault(); select(buttons[next]);
        });
      });
    });
  }

  function setupFeedback(root) {
    root.querySelectorAll("[data-feedback-form]").forEach(function (form) {
      var rejection = form.querySelector("[data-rejection-fields]");
      var reason = rejection.querySelector("select");
      var rebateToggle = form.querySelector('[name="rebate_usado"]');
      var rebate = form.querySelector("[data-rebate-fields]");
      form.querySelectorAll('[name="resultado_final"]').forEach(function (input) {
        input.addEventListener("change", function () {
          var visible = input.value === "rechazada";
          rejection.hidden = !visible; reason.disabled = !visible; reason.required = visible;
        });
      });
      rebateToggle.addEventListener("change", function () {
        rebate.hidden = !rebateToggle.checked; rebate.disabled = !rebateToggle.checked;
        rebate.querySelectorAll("input").forEach(function (input) { input.required = rebateToggle.checked; });
      });
    });
  }

  function setupCopy(root) {
    root.querySelectorAll("[data-copy-target]").forEach(function (button) {
      button.addEventListener("click", function () {
        var field = document.getElementById(button.dataset.copyTarget);
        navigator.clipboard.writeText(field.value).then(function () {
          button.textContent = "Guion copiado";
          window.setTimeout(function () { button.textContent = "Copiar guion"; }, 1800);
        });
      });
    });
  }

  function hydrate(root) {
    setupThemeToggle(root); setupClientExamples(root);
    setupTabs(root); setupFeedback(root); setupCopy(root);
    var focus = root.querySelector("[data-focus-message]");
    if (focus) focus.focus();
    var toast = root.querySelector("[data-toast]");
    if (toast) window.setTimeout(function () { toast.classList.add("leaving"); }, 4200);
  }

  document.addEventListener("htmx:configRequest", csrfHeader);
  document.addEventListener("htmx:beforeRequest", function (event) {
    var workspace = document.getElementById("workspace");
    if (workspace) workspace.setAttribute("aria-busy", "true");
  });
  document.addEventListener("htmx:beforeSwap", function (event) {
    if (event.detail.xhr.status >= 400) {
      event.detail.shouldSwap = true;
      event.detail.isError = false;
    }
  });
  document.addEventListener("htmx:afterRequest", function () {
    var workspace = document.getElementById("workspace");
    if (workspace) workspace.setAttribute("aria-busy", "false");
  });
  document.addEventListener("htmx:afterSwap", function (event) { hydrate(event.detail.target); });
  document.addEventListener("DOMContentLoaded", function () { hydrate(document); });
}());
