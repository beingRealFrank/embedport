// GoatCounter settings: count under a path that includes the host, so this site is separate from other projects
// sharing the same GoatCounter site. Loaded before count.js.
window.goatcounter = { path: function (p) { return location.host + p; } };
