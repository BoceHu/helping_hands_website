#!/usr/bin/env python3
"""Build the static site from data/*.json into public/.

Standard library only — no pip install, no toolchain, no lockfile. Run:

    python3 build.py            # build into public/
    python3 build.py --serve    # build, then serve on http://localhost:8000

Contributors edit data/*.json and never touch HTML. Bad data fails the build
here, before anything is deployed.
"""
import hashlib
import html
import json
import re
import shutil
import sys
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
TPL = ROOT / "templates"
STATIC = ROOT / "static"
OUT = ROOT / "public"

errors = []


def fail(msg):
    errors.append(msg)


def e(s):
    """Escape text coming from data files."""
    return html.escape(str(s or ""), quote=True)


_fingerprints = {}


def asset(rel):
    """Append a content hash to a static path.

    Photos and thumbnails get replaced in place, keeping the same filename, so
    without this the browser keeps serving whatever it cached and the change
    looks like it never happened.
    """
    if not rel:
        return rel
    if rel not in _fingerprints:
        f = STATIC / rel
        h = hashlib.sha256(f.read_bytes()).hexdigest()[:8] if f.is_file() else ""
        _fingerprints[rel] = f"{rel}?v={h}" if h else rel
    return _fingerprints[rel]


def load(name):
    p = DATA / name
    if not p.exists():
        sys.exit(f"missing {p}")
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as ex:
        sys.exit(f"{name}: invalid JSON at line {ex.lineno}, column {ex.colno}: {ex.msg}")


# ------------------------------------------------------------------ validate

def validate(site, people, pubs):
    for i, p in enumerate(people):
        for k in ("name", "section", "slug"):
            if not p.get(k):
                fail(f"people[{i}] missing '{k}'")
        if p.get("photo") and not (STATIC / p["photo"]).exists():
            fail(f"people[{i}] ({p.get('name')}): photo not found: {p['photo']}")
    known = {s["key"] for s in site["people_sections"]}
    for p in people:
        if p.get("section") not in known:
            fail(f"{p.get('name')}: unknown section '{p.get('section')}'")

    # A section ordered by start date is only correct if everyone in it has one,
    # so a forgotten `start` fails the build instead of silently sorting last.
    for sec in site["people_sections"]:
        if "start" not in sec.get("sort", ""):
            continue
        for p in people:
            if p.get("section") != sec["key"]:
                continue
            s = p.get("start", "")
            if not s:
                fail(f"{p['name']}: section '{sec['key']}' is sorted by start date, "
                     f"so this entry needs a \"start\" (\"YYYY\" or \"YYYY-MM\")")
            elif not re.fullmatch(r"\d{4}(-\d{2})?", s):
                fail(f"{p['name']}: start \"{s}\" must be \"YYYY\" or \"YYYY-MM\"")

    for i, p in enumerate(pubs):
        for k in ("title", "authors", "venue"):
            if not p.get(k):
                fail(f"publications[{i}] ({p.get('id', '?')}) missing '{k}'")
        if p.get("thumb") and not (STATIC / p["thumb"]).exists():
            fail(f"publications[{i}] ({p.get('id')}): thumb not found: {p['thumb']}")
        for l in p.get("links", []):
            if not l.get("url"):
                fail(f"publications[{i}] ({p.get('id')}): link '{l.get('label')}' has no url")


# -------------------------------------------------------------------- render

def norm_name(n):
    """'Yaoyao(Freax) Qian' -> 'yaoyao qian', for matching authors to members."""
    n = unicodedata.normalize("NFKD", n).encode("ascii", "ignore").decode()
    n = re.sub(r"\([^)]*\)", " ", n)
    n = re.sub(r"[^\w\s]", " ", n).lower()
    return re.sub(r"\s+", " ", n).strip()


def author_line(authors, member_names):
    out = []
    for a in authors:
        star = "*" if a.rstrip().endswith("*") else ""
        clean = a.rstrip("*").strip()
        if norm_name(clean) in member_names:
            out.append(f'<span class="me">{e(clean)}{star}</span>')
        else:
            out.append(e(clean) + star)
    return ", ".join(out)


def person_card(p):
    name = e(p["name"])
    link = p.get("site", "")
    img = (f'<img src="{e(asset(p["photo"]))}" alt="{name}" loading="lazy" width="300" height="300">'
           if p.get("photo") else "")
    if link:
        img = f'<a href="{e(link)}">{img}</a>' if img else ""
        nm = f'<a href="{e(link)}">{name}</a>'
    else:
        nm = name
    social = ""
    labels = {"envelope": "Email", "google-scholar": "Scholar", "github": "GitHub",
              "twitter": "X", "linkedin": "LinkedIn", "researchgate": "RG"}
    if p.get("social"):
        items = "".join(
            f'<a href="{e(u)}">{labels.get(k, k.title())}</a>'
            for k, u in p["social"].items() if u)
        if items:
            social = f'<div class="person-social">{items}</div>'
    role = f'<p class="person-role">{e(p["role"])}</p>' if p.get("role") else ""
    return (f'<article class="member">{img}<h3>{nm}</h3>{role}{social}</article>')


def faculty_block(p):
    name = e(p["name"])
    link = p.get("site", "")
    nm = f'<a href="{e(link)}">{name}</a>' if link else name
    img = ""
    if p.get("photo"):
        i = f'<img src="{e(asset(p["photo"]))}" alt="{name}" width="360" height="360">'
        img = f'<a href="{e(link)}">{i}</a>' if link else i
    bio = f'<p>{e(p["bio"])}</p>' if p.get("bio") else ""
    social = ""
    labels = {"envelope": "Email", "google-scholar": "Google Scholar", "github": "GitHub",
              "twitter": "X", "linkedin": "LinkedIn"}
    if p.get("social"):
        items = "".join(f'<a href="{e(u)}">{labels.get(k, k.title())}</a>'
                        for k, u in p["social"].items() if u)
        social = f'<div class="person-social">{items}</div>'
    return (f'<div class="faculty">{img}<div><h3>{nm}</h3>'
            f'<p class="person-role">{e(p["role"])}</p>{bio}{social}</div></div>')


def surname(p):
    return p["name"].split()[-1].lower()


def sort_people(group, spec):
    """spec: 'name', 'start', '-start', 'year', '-year'. A leading '-' means
    descending. Ties always fall back to surname, A-Z."""
    desc = spec.startswith("-")
    field = spec.lstrip("-")
    group.sort(key=surname)                      # stable secondary key
    if field != "name":
        group.sort(key=lambda p: p.get(field) or "", reverse=desc)
    elif desc:
        group.reverse()
    return group


def alumni_item(p):
    name = e(p["name"])
    nm = f'<a href="{e(p["site"])}">{name}</a>' if p.get("site") else name
    # degree/year come from Alumni.md; `role` is the fallback for profiles
    # that were never listed there.
    bits = [b for b in (p.get("degree"), p.get("year")) if b]
    meta = ", ".join(bits) or p.get("role", "")
    if p.get("now"):
        meta = f"{meta} · Now {p['now']}" if meta else f"Now {p['now']}"
    tail = f'<span class="person-role">{e(meta)}</span>' if meta else ""
    return f"<li>{nm}{tail}</li>"


def pub_item(p, member_names):
    thumb = (f'<img class="pub-thumb" src="{e(asset(p["thumb"]))}" alt="" loading="lazy">'
             if p.get("thumb") else '<div class="pub-thumb"></div>')
    links = p.get("links", [])
    primary = next((l["url"] for l in links
                    if l["label"] in ("Website", "Project")), None) \
        or next((l["url"] for l in links if l["label"] == "PDF"), None)
    title = e(p["title"])
    title_html = f'<a href="{e(primary)}">{title}</a>' if primary else title
    link_row = ""
    if links:
        link_row = '<div class="pub-links">' + "".join(
            f'<a href="{e(l["url"])}">{e(l["label"])}</a>' for l in links) + "</div>"
    award = f'<span class="pub-award">{e(p["award"])}</span>' if p.get("award") else ""
    return (
        f'<li class="pub">{thumb}<div>'
        f'<h3 class="pub-title">{title_html}</h3>'
        f'<p class="pub-authors">{author_line(p["authors"], member_names)}</p>'
        f'<p class="pub-venue">{e(p["venue"])}{award}</p>'
        f'{link_row}</div></li>'
    )


# ---------------------------------------------------------------- page bodies

def page_home(site, people, pubs):
    h = site["hero"]
    head = "<br>".join(e(x) for x in h["headline"])
    links = "".join(f'<a href="{e(l["href"])}">{e(l["label"])}</a>' for l in h["links"])
    ext = " · ".join(f'<a href="{e(l["href"])}">{e(l["label"])}</a>'
                     for l in h.get("external", []))
    visual = ""
    if h.get("image") and (STATIC / h["image"]).exists():
        cap = (f'<figcaption>{e(h["image_caption"])}</figcaption>'
               if h.get("image_caption") else "")
        visual = (f'<figure class="hero-figure">'
                  f'<img src="{e(asset(h["image"]))}" alt="{e(h["image_alt"])}">'
                  f'{cap}</figure>')
    logo = ""
    if h.get("logo") and (STATIC / h["logo"]).exists():
        logo = (f'<div class="hero-logo">'
                f'<img src="{e(asset(h["logo"]))}" alt="{e(h.get("logo_alt", ""))}">'
                f'</div>')
    return f"""<section class="hero">
  <div class="hero-copy">
    <h1>{head}</h1>
    <p class="lede">{h["lede"]}</p>
    <p class="hero-body">{e(h["body"])}</p>
    <div class="text-links">{links}</div>
    <p class="hero-external">{ext}</p>
  </div>
  {logo}
</section>
{visual}"""


def page_research(site, people, pubs):
    member_names = {norm_name(p["name"]) for p in people}
    items = "\n".join(pub_item(p, member_names) for p in pubs)
    code = "".join(
        f'<li><h3><a href="{e(c["url"])}">{e(c["name"])}</a></h3>'
        f'<p>{e(c["blurb"])}</p></li>' for c in site.get("code", []))
    vids = "".join(
        f'<figure><div class="frame"><iframe src="https://www.youtube.com/embed/{e(v["id"])}"'
        f' title="{e(v["title"])}" loading="lazy" allowfullscreen></iframe></div>'
        f'<figcaption>{e(v["title"])}<span>{e(v.get("note", ""))}</span></figcaption></figure>'
        for v in site.get("videos", []))
    return f"""<h1 class="page-title">Research</h1>
<p class="page-intro">We develop perception, planning, and control algorithms for robot
manipulation, with a focus on symmetry and equivariance in robot learning.</p>

<section class="section">
  <h2 class="section-title">Publications</h2>
  <p class="section-note">{len(pubs)} papers, newest first. Lab members in bold.</p>
  <ol class="pub-list">
{items}
  </ol>
</section>

<section class="section">
  <h2 class="section-title">Code</h2>
  <ul class="card-list">{code}</ul>
</section>

<section class="section">
  <h2 class="section-title">Talks &amp; Videos</h2>
  <div class="video-grid">{vids}</div>
</section>"""


def page_lab(site, people, pubs):
    by = {}
    for p in people:
        by.setdefault(p["section"], []).append(p)
    parts = []
    for sec in site["people_sections"]:
        group = by.get(sec["key"], [])
        if not group:
            continue
        sort_people(group, sec.get("sort", "name"))
        style = sec.get("style", "grid")
        if style == "faculty":
            body = "".join(faculty_block(p) for p in group)
        elif style == "list":
            body = ('<ul class="alumni-list">'
                    + "".join(alumni_item(p) for p in group) + "</ul>")
        else:
            body = ('<div class="people-grid">'
                    + "".join(person_card(p) for p in group) + "</div>")
        parts.append(f'<section class="section"><h2 class="section-title">'
                     f'{e(sec["title"])}</h2>{body}</section>')

    return ('<h1 class="page-title">Lab</h1>\n'
            '<p class="page-intro">The Helping Hands Lab is part of the Khoury College of '
            'Computer Sciences at Northeastern University.</p>\n' + "\n".join(parts))


def opening_block(o):
    parts = [f'<h3>{e(o["title"])}</h3>', f'<p>{e(o["body"])}</p>']
    if o.get("contact"):
        parts.append(f'<p><a href="mailto:{e(o["contact"])}">{e(o["contact"])}</a></p>')
    if o.get("link"):
        parts.append(f'<p class="opening-link">'
                     f'<a href="{e(o["link"]["href"])}">{e(o["link"]["label"])}</a></p>')
    return '<div class="opening">' + "".join(parts) + "</div>"


def page_join(site, people, pubs):
    j = site["join"]
    ops = "".join(opening_block(o) for o in j["openings"])
    return f"""<h1 class="page-title">Join Us</h1>
<p class="page-intro">{e(j["intro"])}</p>
{ops}"""


PAGES = [
    ("index.html",    "Home",     page_home,
     "The Helping Hands Lab at Northeastern University: robot manipulation, "
     "robot learning, and equivariant methods."),
    ("research.html", "Research", page_research,
     "Publications, open-source code, and talks from the Helping Hands Lab."),
    ("lab.html",      "Lab",      page_lab,
     "People of the Helping Hands Lab at Northeastern University."),
    ("join.html",     "Join Us",  page_join,
     "Open postdoc and PhD positions in the Helping Hands Lab."),
]


def main():
    site = load("site.json")
    people = load("people.json")
    pubs = load("publications.json")

    validate(site, people, pubs)
    if errors:
        print(f"build failed — {len(errors)} problem(s):", file=sys.stderr)
        for x in errors:
            print("  -", x, file=sys.stderr)
        sys.exit(1)

    base = (TPL / "base.html").read_text(encoding="utf-8")
    footer = "\n".join(f"    <p>{l}</p>" for l in site["footer"]["lines"])

    if OUT.exists():
        shutil.rmtree(OUT)
    shutil.copytree(STATIC, OUT)

    for filename, label, fn, desc in PAGES:
        nav = "\n".join(
            f'      <a href="{e(n["href"])}"'
            + (' aria-current="page"' if n["href"] == filename else "")
            + f'>{e(n["label"])}</a>'
            for n in site["nav"])
        title = site["title"] if filename == "index.html" \
            else f'{label} · {site["title"]}'
        page = (base
                .replace("{{page_title}}", e(title))
                .replace("{{description}}", e(desc))
                .replace("{{nav}}", nav)
                .replace("{{content}}", fn(site, people, pubs))
                .replace("{{footer}}", footer)
                .replace("{{css}}", e(asset("css/style.css")))
                .replace("{{favicon}}", e(asset("img/favicon.png"))))
        (OUT / filename).write_text(page, encoding="utf-8")

    # Stubs for the Hugo-era URLs that are still live and may be linked from
    # elsewhere. Local PDFs keep their original path, so they need no stub.
    for src, r in site.get("redirects", {}).items():
        d = OUT / src
        d.mkdir(parents=True, exist_ok=True)
        (d / "index.html").write_text(
            '<!DOCTYPE html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
            f'<title>Moved — {e(site["title"])}</title>\n'
            f'<link rel="canonical" href="{e(r["to"])}">\n'
            f'<meta http-equiv="refresh" content="0; url={e(r["to"])}">\n'
            '<meta name="robots" content="noindex">\n</head>\n<body>\n'
            f'<p>This page has moved to <a href="{e(r["to"])}">{e(r["label"])}</a>.</p>\n'
            '</body>\n</html>\n', encoding="utf-8")

    total = sum(f.stat().st_size for f in OUT.rglob("*") if f.is_file())
    print(f"built {len(PAGES)} pages -> {OUT}")
    print(f"  {len(people)} people, {len(pubs)} publications")
    print(f"  {sum(1 for _ in OUT.rglob('*') if _.is_file())} files, {total/1e6:.1f} MB")

    if "--serve" in sys.argv:
        import http.server, socketserver, functools
        h = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(OUT))
        with socketserver.TCPServer(("", 8000), h) as httpd:
            print("\nserving http://localhost:8000  (ctrl-c to stop)")
            httpd.serve_forever()


if __name__ == "__main__":
    main()
