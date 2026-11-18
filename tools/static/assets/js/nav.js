// Collapsible site menu for narrow screens.
(function () {
  var toggle = document.querySelector(".sidenav__toggle");
  if (!toggle) return;
  toggle.addEventListener("click", function () {
    var open = toggle.getAttribute("aria-expanded") === "true";
    toggle.setAttribute("aria-expanded", String(!open));
  });
})();
