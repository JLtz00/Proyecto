(function () {
  "use strict";
  var preferred = "";
  try { preferred = window.localStorage.getItem("nbo-advisor-theme") || ""; } catch (error) {}
  if (preferred !== "light" && preferred !== "dark") {
    preferred = window.matchMedia && window.matchMedia("(prefers-color-scheme: light)").matches
      ? "light" : "dark";
  }
  document.documentElement.dataset.theme = preferred;
}());
