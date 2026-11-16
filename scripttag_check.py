#!/usr/bin/env python3
"""scripttag-check: find a Shopify store's script tags and map each to its replacement.

Shopify stops running storefront script tags on 2027-03-01
(https://shopify.dev/changelog/posts/online-store-script-tags-deprecation).

Two modes, no third-party dependencies:

  scan  <store URL or saved page source> ...
        Reads the public storefront HTML. Shopify injects every active
        online-store script tag through the `asyncLoad` loader in the page
        header, so this lists all of them, from every app, with no credentials.

  api   --shop example.myshopify.com   (token in SHOPIFY_ADMIN_TOKEN)
        Calls the Admin GraphQL `scriptTags` query. Shopify returns only the
        script tags owned by the app whose token you use, so this mode is for
        app developers auditing their own installs. It also shows display
        scope (ONLINE_STORE / ORDER_STATUS / ALL), which a page scan cannot.

Output is a table, or JSON with --json. Exit status 0 = nothing to migrate,
1 = script tags found, 2 = error.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
UA = "Mozilla/5.0 (compatible; scripttag-check/1.0; +https://shopify.dev/docs/apps/build/online-store/script-tag-deprecation)"
API_VERSION = "2026-10"

ANALYTICS_HINTS = re.compile(
    r"(pixel|analytics|track|tracking|beacon|tag\.js|dtag|gtag|gtm|fbevents|conversion|attribution|telemetry|collect|insight|clarity|hotjar|heap|segment|affiliate|refer)",
    re.I,
)

REPLACEMENTS = {
    "web_pixel": {
        "label": "Web pixel (app extension)",
        "why": "The script only collects events or conversions; a web pixel runs in Shopify's sandbox and needs no theme activation.",
        "doc": "https://shopify.dev/docs/apps/build/marketing-analytics/build-web-pixels",
    },
    "app_embed": {
        "label": "Theme app extension: app embed block",
        "why": "The script renders or changes something on storefront pages; an app embed block loads it on vintage and Online Store 2.0 themes once the merchant switches it on in the theme editor.",
        "doc": "https://shopify.dev/docs/apps/build/online-store/theme-app-extensions",
    },
    "app_embed_and_pixel": {
        "label": "App embed block + web pixel",
        "why": "The script both renders UI and tracks events; split the UI into an app embed block and the tracking into a web pixel.",
        "doc": "https://shopify.dev/docs/apps/build/online-store/script-tag-deprecation/storefront",
    },
    "customer_account_ui": {
        "label": "Customer account UI extension (Order status page)",
        "why": "Order status page script tags follow the earlier schedule; the replacement is a customer account UI extension.",
        "doc": "https://shopify.dev/docs/apps/build/online-store/script-tag-deprecation",
    },
    "theme_code": {
        "label": "Move into theme code, or ask the vendor for an app",
        "why": "Admin-created custom apps cannot use app extensions; Shopify's guidance is theme code or a real app.",
        "doc": "https://shopify.dev/docs/apps/build/online-store/script-tag-deprecation/storefront",
    },
}


def load_signatures() -> list[dict]:
    path = HERE / "signatures.json"
    if not path.exists():
        return []
    return json.loads(path.read_text())


SIGNATURES = load_signatures()


PROXY_RE = re.compile(r"^/proxy/[0-9a-f]{16,}/(.+)$")


def origin_url(src: str) -> str:
    """Script tags created with cache=true are served from cdn.shopify.com/proxy/<hash>/<host>/<path>."""
    parts = urllib.parse.urlsplit(src)
    if parts.hostname == "cdn.shopify.com":
        m = PROXY_RE.match(parts.path)
        if m:
            return "https://" + m.group(1) + ("?" + parts.query if parts.query else "")
    return src


def identify(src: str) -> dict:
    src = origin_url(src)
    host = urllib.parse.urlsplit(src).hostname or ""
    for sig in SIGNATURES:
        for pat in sig["match"]:
            if pat in host or pat in src:
                return sig
    return {}


def replacement_for(src: str, sig: dict, display_scope: str | None = None) -> str:
    if display_scope == "ORDER_STATUS":
        return "customer_account_ui"
    if sig.get("replacement"):
        return sig["replacement"]
    return "web_pixel" if ANALYTICS_HINTS.search(src) else "app_embed"


# --- scan mode -------------------------------------------------------------

ASYNC_RE = re.compile(r"function asyncLoad\(\)\s*\{.*?var urls\s*=\s*(\[.*?\]);", re.S)


def extract_script_tags(html: str) -> list[str]:
    """Return the script tag URLs Shopify's asyncLoad loader injects, in order, de-duplicated."""
    out: list[str] = []
    for m in ASYNC_RE.finditer(html):
        try:
            urls = json.loads(m.group(1))
        except json.JSONDecodeError:
            urls = re.findall(r'"((?:[^"\\]|\\.)*)"', m.group(1))
            urls = [json.loads(f'"{u}"') for u in urls]
        for u in urls:
            if u not in out:
                out.append(u)
    return out


def is_shopify(html: str) -> bool:
    return "cdn.shopify.com" in html or "Shopify.shop" in html or "shopify-digital-wallet" in html


def shop_domain(html: str) -> str | None:
    m = re.search(r'Shopify\.shop\s*=\s*"([^"]+)"', html)
    return m.group(1) if m else None


def fetch(url: str, timeout: int = 25) -> str:
    if not re.match(r"^https?://", url):
        url = "https://" + url
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "text/html"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", errors="replace")


def analyse(srcs: list[str], scopes: dict[str, str] | None = None) -> list[dict]:
    rows = []
    for src in srcs:
        sig = identify(src)
        scope = (scopes or {}).get(src)
        rep = replacement_for(src, sig, scope)
        rows.append({
            "src": src,
            "host": urllib.parse.urlsplit(origin_url(src)).hostname,
            "cached_by_shopify": origin_url(src) != src,
            "app": sig.get("app"),
            "vendor": sig.get("vendor"),
            "display_scope": scope,
            "replacement": rep,
            "replacement_label": REPLACEMENTS[rep]["label"],
            "why": REPLACEMENTS[rep]["why"],
            "doc": REPLACEMENTS[rep]["doc"],
            "vendor_ships_embed": bool(sig.get("embed_shipped")),
        })
        if sig.get("embed_shipped"):
            rows[-1]["replacement_label"] = "Vendor already ships an app embed: switch it on in the theme editor, confirm it loads once, then remove the old script tag"
    return rows


def scan_target(target: str) -> dict:
    if os.path.exists(target):
        html = Path(target).read_text(errors="replace")
        source = "file"
    else:
        html = fetch(target)
        source = "url"
    srcs = extract_script_tags(html)
    return {
        "target": target,
        "source": source,
        "shopify": is_shopify(html),
        "myshopify_domain": shop_domain(html),
        "script_tags": analyse(srcs),
    }


# --- api mode --------------------------------------------------------------

QUERY = """
query($after: String) {
  scriptTags(first: 100, after: $after) {
    edges { cursor node { id src displayScope cache createdAt updatedAt } }
    pageInfo { hasNextPage }
  }
}"""


def api_list(shop: str, token: str, version: str = API_VERSION) -> list[dict]:
    url = f"https://{shop}/admin/api/{version}/graphql.json"
    nodes, after = [], None
    while True:
        body = json.dumps({"query": QUERY, "variables": {"after": after}}).encode()
        req = urllib.request.Request(url, data=body, method="POST", headers={
            "Content-Type": "application/json",
            "X-Shopify-Access-Token": token,
            "User-Agent": UA,
        })
        with urllib.request.urlopen(req, timeout=30) as r:
            data = json.loads(r.read())
        if data.get("errors"):
            raise RuntimeError(json.dumps(data["errors"]))
        conn = data["data"]["scriptTags"]
        nodes += [e["node"] for e in conn["edges"]]
        if not conn["pageInfo"]["hasNextPage"]:
            return nodes
        after = conn["edges"][-1]["cursor"]


def api_target(shop: str, token: str) -> dict:
    nodes = api_list(shop, token)
    scopes = {n["src"]: n["displayScope"] for n in nodes}
    rows = analyse([n["src"] for n in nodes], scopes)
    for row, n in zip(rows, nodes):
        row.update({"id": n["id"], "cache": n["cache"], "created_at": n["createdAt"], "updated_at": n["updatedAt"]})
        if n["displayScope"] == "ALL":
            row["replacement_label"] += " + customer account UI extension (Order status)"
    return {"target": shop, "source": "admin_api", "shopify": True, "myshopify_domain": shop, "script_tags": rows}


# --- output ----------------------------------------------------------------

def render(report: dict) -> str:
    lines = [f"\n{report['target']}" + (f"  ({report['myshopify_domain']})" if report.get("myshopify_domain") else "")]
    if not report["shopify"]:
        lines.append("  Not a Shopify storefront (or the page was blocked).")
        return "\n".join(lines)
    tags = report["script_tags"]
    if not tags:
        lines.append("  No script tags found. Nothing breaks on 2027-03-01 from script tags.")
        return "\n".join(lines)
    lines.append(f"  {len(tags)} script tag(s) will stop running on 2027-03-01:")
    for i, t in enumerate(tags, 1):
        who = t["app"] or "Unidentified app"
        if t["vendor"]:
            who += f" ({t['vendor']})"
        lines.append(f"  {i}. {who}")
        lines.append(f"     src:  {t['src']}")
        if t.get("display_scope"):
            lines.append(f"     scope: {t['display_scope']}")
        lines.append(f"     move to: {t['replacement_label']}")
        lines.append(f"     docs: {t['doc']}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="scripttag-check", description=__doc__.split("\n\n")[0])
    sub = p.add_subparsers(dest="mode", required=True)
    s = sub.add_parser("scan", help="scan public storefront pages or saved page source")
    s.add_argument("targets", nargs="+")
    s.add_argument("--json", action="store_true")
    a = sub.add_parser("api", help="list your app's script tags with the Admin API")
    a.add_argument("--shop", required=True, help="example.myshopify.com")
    a.add_argument("--token-env", default="SHOPIFY_ADMIN_TOKEN", help="env var holding the Admin API token")
    a.add_argument("--json", action="store_true")
    args = p.parse_args(argv)

    reports, failed = [], False
    if args.mode == "scan":
        for t in args.targets:
            try:
                reports.append(scan_target(t))
            except (urllib.error.URLError, OSError, ValueError) as e:
                failed = True
                hint = ""
                if isinstance(e, urllib.error.HTTPError) and e.code in (403, 429, 430):
                    hint = " (the store blocked the request; open it in a browser, save the page source, and run: scan page.html)"
                reports.append({"target": t, "error": str(e) + hint})
    else:
        token = os.environ.get(args.token_env)
        if not token:
            print(f"Set {args.token_env} to an Admin API access token.", file=sys.stderr)
            return 2
        try:
            reports.append(api_target(args.shop, token))
        except (urllib.error.URLError, RuntimeError, KeyError) as e:
            print(f"API error: {e}", file=sys.stderr)
            return 2

    if args.json:
        print(json.dumps(reports if len(reports) > 1 else reports[0], indent=2))
    else:
        for r in reports:
            print(f"\n{r['target']}\n  error: {r['error']}" if "error" in r else render(r))
    if failed and not any(r.get("script_tags") for r in reports):
        return 2
    return 1 if any(r.get("script_tags") for r in reports) else 0


if __name__ == "__main__":
    sys.exit(main())
