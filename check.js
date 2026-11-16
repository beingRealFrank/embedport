// Embedport in-browser script tag check. Parses pasted page source; makes no network requests
// except fetching signatures.json from this same site.
(function () {
  'use strict';
  var DEADLINE = Date.UTC(2027, 2, 1);
  var days = Math.max(0, Math.ceil((DEADLINE - Date.now()) / 86400000));
  var d = document.getElementById('days');
  if (d) d.textContent = String(days);

  var REP = {
    web_pixel: 'Web pixel (app extension)',
    app_embed: 'Theme app extension: app embed block',
    app_embed_and_pixel: 'App embed block + web pixel',
    theme_code: 'Move into theme code, or ask the vendor for an app'
  };
  var ANALYTICS = /(pixel|analytics|track|tracking|beacon|tag\.js|dtag|gtag|gtm|fbevents|conversion|attribution|telemetry|collect|insight|clarity|hotjar|heap|segment|affiliate|refer)/i;
  var sigs = [];
  fetch('signatures.json').then(function (r) { return r.json(); }).then(function (j) { sigs = j; }).catch(function () {});

  function originUrl(src) {
    var m = /^(?:https?:)?\/\/cdn\.shopify\.com\/proxy\/[0-9a-f]{16,}\/([^?]+)(\?.*)?$/.exec(src);
    return m ? 'https://' + m[1] + (m[2] || '') : src;
  }
  function host(u) {
    try { return new URL(u, 'https://x.invalid').hostname; } catch (e) { return ''; }
  }
  function identify(src) {
    var o = originUrl(src), h = host(o);
    for (var i = 0; i < sigs.length; i++) {
      for (var k = 0; k < sigs[i].match.length; k++) {
        var p = sigs[i].match[k];
        if (h.indexOf(p) !== -1 || o.indexOf(p) !== -1) return sigs[i];
      }
    }
    return null;
  }
  function extract(html) {
    var re = /function asyncLoad\(\)\s*\{[\s\S]*?var urls\s*=\s*(\[[\s\S]*?\]);/g, m, out = [];
    while ((m = re.exec(html))) {
      var urls;
      try { urls = JSON.parse(m[1]); } catch (e) { urls = []; }
      urls.forEach(function (u) { if (out.indexOf(u) === -1) out.push(u); });
    }
    return out;
  }
  function el(tag, cls, text) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text != null) e.textContent = text;
    return e;
  }

  document.getElementById('run').addEventListener('click', function () {
    var html = document.getElementById('src').value;
    var out = document.getElementById('out');
    out.textContent = '';
    if (!html.trim()) { out.appendChild(el('p', 'warn', 'Paste the page source first.')); return; }
    var shopM = /Shopify\.shop\s*=\s*"([^"]+)"/.exec(html);
    if (!shopM && html.indexOf('cdn.shopify.com') === -1) {
      out.appendChild(el('p', 'warn', "This doesn't look like a Shopify storefront page. Paste the full page source of your store's homepage."));
      return;
    }
    var tags = extract(html);
    var shop = shopM ? shopM[1] : 'your store';
    if (!tags.length) {
      out.appendChild(el('p', 'ok', 'No script tags found on this page. Nothing here breaks on March 1, 2027 because of script tags. (Order status page script tags are not visible in storefront source.)'));
      return;
    }
    out.appendChild(el('p', 'bad', tags.length + ' script tag' + (tags.length > 1 ? 's' : '') + ' on ' + shop + ' will stop running on March 1, 2027 (' + days + ' days).'));
    var table = el('table', 'res');
    var hr = el('tr');
    ['#', 'App', 'Loads', 'Replacement'].forEach(function (h) { hr.appendChild(el('th', null, h)); });
    table.appendChild(hr);
    var summary = ['Script tag check for ' + shop + ' (' + new Date().toISOString().slice(0, 10) + '):'];
    tags.forEach(function (src, i) {
      var sig = identify(src), o = originUrl(src);
      var rep = (sig && sig.replacement) || (ANALYTICS.test(o) ? 'web_pixel' : 'app_embed');
      var repText = (sig && sig.embed_shipped) ? 'Vendor already ships an app embed: switch it on (Theme editor → App embeds)' : REP[rep];
      var name = sig ? sig.app : 'Unidentified (' + host(o) + ')';
      var tr = el('tr');
      tr.appendChild(el('td', null, String(i + 1)));
      tr.appendChild(el('td', null, name));
      var c = el('td', 'src'); c.appendChild(el('code', null, o)); tr.appendChild(c);
      tr.appendChild(el('td', null, repText));
      table.appendChild(tr);
      summary.push((i + 1) + '. ' + name + ' | ' + o + ' | ' + repText);
    });
    out.appendChild(table);
    out.appendChild(el('p', 'small', 'Replacements for unidentified apps are a best guess from the URL. The audit confirms each one with the vendor.'));
    var btn = el('button', 'btn ghost', 'Copy summary');
    btn.type = 'button';
    btn.addEventListener('click', function () {
      navigator.clipboard.writeText(summary.join('\n')).then(function () { btn.textContent = 'Copied'; });
    });
    out.appendChild(btn);
  });
})();
