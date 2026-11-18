"""Rebuild selected Screamscape pages with a responsive layout.

Reads the original NetObjects Fusion pages saved in _source/ (as downloaded
from https://screamscape.com/), pulls out each page's regions (masthead,
welcome blurb, side navigation, "News & Rumors" column, "Track Record" column,
footer) and writes them into a semantic, CSS-Grid based template in docs/.

Content markup inside each text region is kept as-is apart from:
  * ad units and trackers are swapped for neutral placeholders / removed,
  * links to pages in this proof of concept stay local, everything else
    points at the live site,
  * content images load from the live site (layout images are copied locally).

Usage:  python tools/build.py   (needs beautifulsoup4)
"""
from __future__ import annotations

import html
import re
import shutil
import sys
import urllib.request
from pathlib import Path
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup, Comment, NavigableString, Tag

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "_source"
OUT = ROOT / "docs"
LIVE = "https://screamscape.com/"

PAGES = ["index"] + (ROOT / "tools" / "pages.txt").read_text().split()
LOCAL_PAGES = {"index.htm": "index.html", "index.html": "index.html", "": "index.html"}
LOCAL_PAGES.update({f"html/{p}.htm": f"html/{p}.htm" for p in PAGES if p != "index"})

DECOR = re.compile(r"clearpixel|side_corner|bodyLEFT|body2\.gif|footer_border", re.I)
TRACKERS = re.compile(
    r"quantserve|google-analytics|_gaq|infolinks|fastclick|vclk_|adsbygoogle|"
    r"google_ad_|show_ads\.js|jquery\.js|_nof\.js|coop/cse/brand",
    re.I,
)

layout_assets: set[str] = set()  # site-relative paths of images copied locally


# --------------------------------------------------------------------------- urls
def site_path(url: str, page_dir: str) -> str | None:
    """Return the screamscape.com path for url, or None if it is off-site."""
    if not url:
        return None
    url = url.strip()
    if url.startswith(("#", "mailto:", "javascript:", "data:", "tel:")):
        return None
    absolute = urljoin(LIVE + page_dir, url)
    parsed = urlparse(absolute)
    if parsed.netloc.lower() not in ("screamscape.com", "www.screamscape.com"):
        return None
    path = parsed.path.lstrip("/")
    return path + (("?" + parsed.query) if parsed.query else "") + (
        ("#" + parsed.fragment) if parsed.fragment else ""
    )


def rel(target: str, page_dir: str) -> str:
    """Relative URL from a page in page_dir ('' or 'html/') to a docs/ path."""
    return ("../" if page_dir else "") + target


def fix_href(url: str, page_dir: str) -> str:
    sp = site_path(url, page_dir)
    if sp is None:
        return url
    path, _, frag = sp.partition("#")
    if path in LOCAL_PAGES:
        target = LOCAL_PAGES[path]
        if page_dir and target.startswith("html/"):
            target = target[len("html/"):]
            return target + ("#" + frag if frag else "")
        return rel(target, page_dir) + ("#" + frag if frag else "")
    return LIVE + sp


def fix_src(url: str, page_dir: str, local: bool = False) -> str:
    sp = site_path(url, page_dir)
    if sp is None:
        return url.replace("http://", "https://", 1) if url.startswith("http://") else url
    if local:
        layout_assets.add(sp)
        return rel(sp, page_dir)
    return LIVE + sp


# --------------------------------------------------------------------------- helpers
def inner(tag: Tag) -> str:
    return "".join(str(c) for c in tag.contents).strip()


def ad(kind: str, w: int, h: int) -> str:
    return (
        f'<div class="ad ad--{kind}" style="--ad-w:{w}px;--ad-r:{w}/{h}" '
        f'aria-hidden="true"><span>Advertisement {w}&times;{h}</span></div>'
    )


def bg_of(tag: Tag) -> str:
    return tag.get("style") or ""


def clean_fragment(node: Tag, page_dir: str) -> None:
    """Clean a content region in place: ads, trackers, links, images."""
    for c in node.find_all(string=lambda s: isinstance(s, Comment)):
        c.extract()

    # Google AdSense units -> placeholders (keep the float wrapper if any).
    for ins in node.find_all("ins", class_="adsbygoogle"):
        m = re.search(r"width:\s*(\d+)px;\s*height:\s*(\d+)px", ins.get("style", ""))
        w, h = (int(m.group(1)), int(m.group(2))) if m else (336, 280)
        kind = "rect" if w < 600 else "leaderboard"
        ins.replace_with(BeautifulSoup(ad(kind, w, h), "html.parser"))
    for s in node.find_all("script"):
        code = s.string or ""
        m = re.search(r"google_ad_width\s*=\s*(\d+).*?google_ad_height\s*=\s*(\d+)", code, re.S)
        if m:
            s.replace_with(
                BeautifulSoup(ad("sky", int(m.group(1)), int(m.group(2))), "html.parser")
            )
        elif TRACKERS.search(s.get("src", "") + code):
            s.decompose()
    for img in node.find_all("img", src=re.compile("fastclick", re.I)):
        img.decompose()
    # Conversant/Fastclick 300x250 units (script already removed above).
    for ns in node.find_all("noscript"):
        if "fastclick" in str(ns):
            ns.replace_with(BeautifulSoup(ad("rect", 300, 250), "html.parser"))

    # Infolinks in-article spacer tables.
    for inp in node.find_all("input", attrs={"name": "IL_IN_ARTICLE"}):
        t = inp.find_parent("table")
        (t or inp).decompose()

    # Tables that only wrap an ad placeholder -> a simple floated box.
    for t in node.find_all("table"):
        if getattr(t, "decomposed", False):
            continue
        ads = t.find_all("div", class_="ad")
        if ads and not t.get_text(strip=True).replace("Advertisement", "").strip("0123456789× \xa0"):
            align = (t.get("align") or "").lower()
            wrap = BeautifulSoup(
                f'<div class="ad-wrap{" ad-wrap--" + align if align else ""}"></div>', "html.parser"
            ).div
            for a in ads:
                wrap.append(a.extract())
            t.replace_with(wrap)

    # Empty "LayoutRegion" spacer tables left behind by the skyscraper code.
    for t in node.find_all("table", id=re.compile(r"^LayoutRegion")):
        if not t.get_text(strip=True) and not t.find(["img", "iframe", "form"]):
            t.decompose()

    for a in node.find_all(["a", "area"], href=True):
        a["href"] = fix_href(a["href"], page_dir)
    for f in node.find_all("form", action=True):
        f["action"] = f["action"].replace("http://", "https://", 1)
    for img in node.find_all("img", src=True):
        img["src"] = fix_src(img["src"], page_dir)
        img.attrs.pop("border", None)
        if "loading" not in img.attrs:
            img["loading"] = "lazy"
        if img.get("alt") is None:
            img["alt"] = ""
    for el in node.find_all(style=re.compile("url\\(")):
        el["style"] = re.sub(
            r"url\('?([^')]+)'?\)",
            lambda m: f"url('{fix_src(m.group(1), page_dir)}')",
            el["style"],
        )
    for s in node.find_all("script", src=True):
        if s["src"].startswith("//"):
            s["src"] = "https:" + s["src"]
    for ifr in node.find_all("iframe"):
        if "youtube" in ifr.get("src", ""):
            ifr["class"] = ifr.get("class", []) + ["embed-16x9"]
        ifr["loading"] = "lazy"
    # Classify content tables: single-cell wrappers vs real grids.
    for t in node.find_all("table"):
        rows = [r for r in t.find_all("tr") if r.find_parent("table") is t]
        cells = [c for r in rows for c in r.find_all(["td", "th"], recursive=False)]
        t["class"] = t.get("class", []) + (["wrap-table"] if len(cells) <= 1 else ["data-table"])
    # Blank paragraphs the original used to push text below floated boxes;
    # tagged so narrow layouts can collapse runs of them.
    for p in node.find_all("p"):
        if not p.get_text().replace("\xa0", "").strip() and not p.find(
            ["img", "iframe", "script", "blockquote", "div", "table", "input", "form", "video"]
        ):
            p["class"] = p.get("class", []) + ["spacer"]


def collect_blocks(col: Tag) -> list[tuple]:
    """Walk a content column and return its blocks in document order."""
    out: list[tuple] = []

    def walk(n: Tag, in_track: bool) -> None:
        for c in list(n.children):
            if not isinstance(c, Tag):
                continue
            if c.name == "table" and "body_bg" in bg_of(c):
                out.append(("hdr", " ".join(c.get_text(" ").split())))
                continue
            if c.name == "td" and "TextObject" in (c.get("class") or []):
                out.append(("txt", c, in_track))
                continue
            if c.name == "table" and "track_border" in bg_of(c):
                out.append(("track_start",))
                walk(c, True)
                out.append(("track_end",))
                continue
            if c.name == "img" and not DECOR.search(c.get("src", "")):
                out.append(("img", c, in_track))
                continue
            if c.name == "script" and "google_ad_" in (c.string or ""):
                out.append(("sky", in_track))
                continue
            if c.name == "form":
                out.append(("form", c, in_track))
                continue
            walk(c, in_track)

    walk(col, False)
    return out


def render_text(td: Tag, page_dir: str, cls: str) -> str:
    clean_fragment(td, page_dir)
    style = td.get("style", "")
    style = re.sub(r"padding:\s*0px;?", "", style).strip()
    body = inner(td)
    if not BeautifulSoup(body, "html.parser").get_text(strip=True) and "<img" not in body \
            and "ad--" not in body and "<iframe" not in body:
        return ""
    attr = f' style="{html.escape(style)}"' if style else ""
    anchor = f' id="{td.get("id")}"' if td.get("id") else ""
    return f'<div class="{cls}"{anchor}{attr}>{body}</div>'


# --------------------------------------------------------------------------- page
def build(name: str) -> None:
    src_file = SRC / ("index.html" if name == "index" else f"html/{name}.htm")
    page_dir = "" if name == "index" else "html/"
    raw = src_file.read_bytes().decode("cp1252", errors="replace")
    soup = BeautifulSoup(raw, "html.parser")

    title = soup.title.get_text(strip=True) if soup.title else "Screamscape"
    home = rel("index.html", page_dir)

    # ---- masthead
    def img_like(pattern: str) -> Tag:
        return soup.find("img", src=re.compile(pattern, re.I))

    banner = img_like(r"BANNER2008")
    art = soup.find("img", id=re.compile("^Picture"), width="462")
    social = img_like(r"BlueBlock190")
    mission = img_like(r"MISSION2010")
    data_icon = img_like(r"/data\.gif")

    social_links = []
    for area in social.find_next("map").find_all("area"):
        href = area["href"]
        net = "Instagram" if "instagram" in href else "X (Twitter)" if "twitter" in href else "Facebook"
        x1, y1, x2, y2 = (int(v) for v in area["coords"].split(","))
        social_links.append(
            f'<a class="masthead__social-link" href="{href.replace("http://", "https://")}" '
            f'target="_blank" rel="noopener" aria-label="Screamscape on {net}" '
            f'style="--x:{x1 / 190 * 100:.2f}%;--y:{y1}%;--w:{(x2 - x1) / 190 * 100:.2f}%;--h:{y2 - y1}%"></a>'
        )

    welcome_title = soup.find("td", id="Text176")
    welcome_body = welcome_title.find_next("td", class_="TextObject")
    clean_fragment(welcome_body, page_dir)

    # ---- side navigation
    navbar = soup.find("table", id=re.compile(r"^NavigationBar"))
    nav_items = []
    for a in navbar.find_all("a"):
        img = a.find("img")
        href = fix_href(a["href"], page_dir)
        current = ' aria-current="page"' if href in ("#", "") or (
            name == "index" and href == "index.html"
        ) or href == f"{name}.htm" else ""
        nav_items.append(
            f'<li><a href="{href}"{current}><img src="{fix_src(img["src"], page_dir, True)}" '
            f'width="185" height="23" alt="{html.escape(img.get("alt", ""))}"></a></li>'
        )
    for pic in ("side_top.gif", "side_bg.gif", "side_bottom.gif", "bar_vertical_dark.jpg",
                "side_corner2.gif", "body_bg.gif", "bodyLEFT.gif", "body2.gif",
                "track_border210.gif", "footer_border.gif", "bar_vertical_grade2.jpg"):
        layout_assets.add(f"assets/images/{pic}")

    # ---- content columns
    corner = soup.find("img", src=re.compile("side_corner2.gif"), width=re.compile("^10"))
    ctab = corner.find_parent("table").find_next_sibling("table")
    cols = ctab.find("tr").find_all("td", recursive=False)

    def render_column(col: Tag, text_cls: str) -> str:
        parts: list[str] = []
        in_track = False
        for b in collect_blocks(col):
            kind = b[0]
            if kind == "hdr":
                tag = "h1" if text_cls == "news__text" and not parts else "h2"
                parts.append(f'<{tag} class="bar"><span>{html.escape(b[1])}</span></{tag}>')
            elif kind == "track_start":
                parts.append('<div class="track__panel">')
                in_track = True
            elif kind == "track_end":
                parts.append("</div>")
                in_track = False
            elif kind == "txt":
                parts.append(render_text(b[1], page_dir, text_cls))
            elif kind == "img":
                img = b[1]
                parts.append(
                    f'<p class="{text_cls} {text_cls}--image"><img src="{fix_src(img["src"], page_dir)}" '
                    f'width="{img.get("width", "")}" height="{img.get("height", "")}" '
                    f'alt="{html.escape(img.get("alt", ""))}" loading="lazy"></p>'
                )
            elif kind == "sky":
                parts.append(ad("sky", 160, 600))
            elif kind == "form":
                form = b[1]
                clean_fragment(form, page_dir)
                for s in form.find_all("script"):
                    s.decompose()
                q = form.find("input", attrs={"name": "q"})
                if q:
                    q["aria-label"] = "Search Screamscape"
                    q["type"] = "search"
                    q.attrs.pop("size", None)
                parts.append(f'<div class="search">{form}</div>')
        return "\n".join(p for p in parts if p)

    main_html = render_column(cols[0], "news__text")
    track_html = render_column(cols[1], "track__text")

    # ---- left-column skyscraper (below the nav panel)
    left_has_sky = any(
        "google_ad_" in (s.string or "")
        for s in corner.find_parent("td").find_previous_sibling("td").find_all("script")
    ) if corner.find_parent("td").find_previous_sibling("td") else True

    # ---- footer
    hill = img_like(r"graphic_coasterhill")
    copyright_td = soup.find("td", id="Text1164")
    clean_fragment(copyright_td, page_dir)
    copyright_html = inner(copyright_td)

    canonical = LIVE + ("" if name == "index" else f"html/{name}.htm")

    doc = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex, nofollow">
<title>{html.escape(title)}</title>
<link rel="canonical" href="{canonical}">
<link rel="icon" href="{LIVE}favicon.ico">
<link rel="stylesheet" href="{rel('assets/css/screamscape.css', page_dir)}">
<script>document.documentElement.classList.add("js")</script>
<script src="{rel('assets/js/nav.js', page_dir)}" defer></script>
</head>
<body>
<a class="skip-link" href="#main">Skip to content</a>
<div class="site">
  <header class="masthead">
    <div class="masthead__brand">
      <a class="masthead__logo" href="{home}"><img src="{fix_src(banner['src'], page_dir, True)}" width="298" height="100" alt="Screamscape"></a>
      <img class="masthead__art" src="{fix_src(art['src'], page_dir, True)}" width="462" height="100" alt="">
      <div class="masthead__social">
        <img src="{fix_src(social['src'], page_dir, True)}" width="190" height="100" alt="">
        {''.join(social_links)}
      </div>
      <img class="masthead__tagline" src="{fix_src(mission['src'], page_dir, True)}" width="950" height="30" alt="The Ultimate Guide To Theme Parks">
      <div class="masthead__ad">{ad("leaderboard", 728, 90)}</div>
    </div>
    <section class="masthead__welcome" aria-label="Welcome">
      <h2 class="welcome__title"><img src="{fix_src(data_icon['src'], page_dir, True)}" width="18" height="9" alt="">Welcome To Screamscape!</h2>
      <div class="welcome__text">{inner(welcome_body)}</div>
    </section>
  </header>

  <div class="layout">
    <nav class="sidenav" aria-label="Site">
      <button class="sidenav__toggle" type="button" aria-expanded="false" aria-controls="sidenav-menu">
        <span class="sidenav__burger" aria-hidden="true"></span>Menu
      </button>
      <div class="sidenav__panel" id="sidenav-menu">
        <ul class="sidenav__list">
          {''.join(nav_items)}
        </ul>
      </div>
      {ad("sky", 160, 600) if left_has_sky else ""}
    </nav>

    <div class="content">
      <main class="news" id="main">
{main_html}
      </main>
      <aside class="track" aria-label="Park details">
{track_html}
      </aside>
    </div>
  </div>

  <footer class="footer">
    <img class="footer__hill" src="{fix_src(hill['src'], page_dir, True)}" width="195" height="44" alt="">
    <div class="footer__text">{copyright_html}</div>
  </footer>
</div>
</body>
</html>
"""
    dest = OUT / ("index.html" if name == "index" else f"html/{name}.htm")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(doc, encoding="utf-8")
    print("built", dest.relative_to(ROOT))


def fetch_assets() -> None:
    for sp in sorted(layout_assets):
        dest = OUT / sp
        if dest.exists():
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        req = urllib.request.Request(LIVE + sp, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=30) as r:
            dest.write_bytes(r.read())
        print("fetched", sp)


def main() -> None:
    OUT.mkdir(exist_ok=True)
    for name in PAGES:
        build(name)
    fetch_assets()
    for static in ("assets/css/screamscape.css", "assets/js/nav.js"):
        s = ROOT / "tools" / "static" / static
        d = OUT / static
        d.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(s, d)
    (OUT / ".nojekyll").write_text("")
    (OUT / "robots.txt").write_text("User-agent: *\nDisallow: /\n")


if __name__ == "__main__":
    sys.exit(main())
