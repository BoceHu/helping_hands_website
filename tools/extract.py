#!/usr/bin/env python3
"""One-time migration: Hugo/Wowchemy content tree -> data/*.json + static images.

Run once (needs pyyaml + macOS `sips`). The generated JSON is what the site is
built from afterwards; this script is not part of the build.

    ./.venv/bin/python tools/extract.py ../helping_hands_website
"""
import json
import re
import shutil
import subprocess
import sys
import unicodedata
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent.parent
DATA = HERE / "data"
IMG_PEOPLE = HERE / "static/img/people"
IMG_PUBS = HERE / "static/img/pubs"
FILES = HERE / "static/files"

# Wowchemy publication_types -> our kind
PUB_KIND = {
    "1": "conference", "2": "journal", "3": "preprint",
    "4": "report", "5": "book", "6": "chapter", "7": "thesis", "8": "patent",
}

# user_groups -> our section, refined by role for current members
GROUP_OF = {
    "Our intrepid leader (i.e. the PI)": "faculty",
    "Students": "current",
    "Visitors": "current",
    "Ph.D. Alumni": "phd_alumni",
    "Alumni": "alumni",
}

warnings = []


def warn(msg):
    warnings.append(msg)


def slugify(s):
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    s = re.sub(r"[^\w\s-]", "", s).strip().lower()
    return re.sub(r"[-\s]+", "-", s)


def front_matter(path):
    text = path.read_text(encoding="utf-8", errors="replace")
    # Some files start with a blank line before the `---`; Hugo tolerates it.
    m = re.match(r"^\s*---\s*\n(.*?)\n---\s*\n?(.*)$", text, re.S)
    if not m:
        warn(f"{path}: no front matter")
        return {}, ""
    try:
        fm = yaml.safe_load(m.group(1)) or {}
    except yaml.YAMLError as e:
        warn(f"{path}: YAML error: {e}")
        return {}, m.group(2)
    return fm, m.group(2)


def clean_venue(short, full):
    """'In *IROS 2021*' -> 'IROS 2021'; also unify ICRA'25 -> ICRA 2025."""
    v = (short or full or "").strip()
    v = re.sub(r"^In\s+", "", v)
    v = v.replace("*", "").strip()
    v = re.sub(r"^\((.*)\)$", r"\1", v).strip()
    # The source mixes "CoRL 2023" and "CoRL'23" for the same venue.
    v = re.sub(r"'(\d{2})\b", lambda m: " 20" + m.group(1), v)
    return re.sub(r"\s+", " ", v).strip()


def fix_url(u, who=""):
    """Two profiles store a bare host, which browsers treat as a relative link."""
    u = (u or "").strip()
    if u and not u.startswith(("http://", "https://", "mailto:", "/")):
        warn(f"{who}: URL missing scheme -> fixed (https://{u})")
        u = "https://" + u
    return u


ALUMNI_RE = re.compile(
    r"^-\s+"
    r"(?:\[(?P<lname>[^\]]+)\]\((?P<lurl>[^)]+)\)|(?P<pname>[^,\[]+?))"
    r"\s*,\s*(?P<rest>.+)$"
)


def parse_alumni_md(path):
    """content/people/Alumni.md holds graduation year and current position --
    the People widget never showed it. Merge it back in."""
    if not path.exists():
        warn(f"{path}: not found, alumni 'now' info skipped")
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.rstrip()
        if not line.startswith("- "):
            continue
        m = ALUMNI_RE.match(line)
        if not m:
            warn(f"Alumni.md: could not parse {line[:70]!r}")
            continue
        name = (m.group("lname") or m.group("pname") or "").strip()
        site = fix_url(m.group("lurl") or "", f"Alumni.md/{name}")
        rest = m.group("rest").strip()

        now = ""
        # most lines separate the current position with ". Now", one uses ", Now"
        nm = re.search(r"[.,]\s*Now\b\s*(.*)$", rest, re.I)
        if nm:
            now = nm.group(1).strip().rstrip(".")
            rest = rest[:nm.start()].strip()
        # The source markdown wraps lines, leaving stray " - " inside names.
        now = re.sub(r"\s+-\s+", " ", now)
        rest = rest.rstrip(". ").strip()

        ym = re.search(r"\b(19|20)\d{2}\b", rest)
        year = ym.group(0) if ym else ""
        degree = re.sub(r",?\s*\b(19|20)\d{2}\b", "", rest).strip().rstrip(",")

        out.append({"name": name, "site": site, "degree": degree,
                    "year": year, "now": now})
    return out


def resize(src, dst, max_px):
    dst.parent.mkdir(parents=True, exist_ok=True)
    r = subprocess.run(
        ["sips", "--resampleHeightWidthMax", str(max_px), str(src), "--out", str(dst)],
        capture_output=True, text=True,
    )
    if r.returncode != 0:
        warn(f"sips failed for {src}: {r.stderr.strip()[:120]}")
        shutil.copy2(src, dst)


def extract_people(src_root):
    out = []
    for d in sorted((src_root / "content/authors").iterdir()):
        if not d.is_dir():
            continue
        idx = d / "_index.md"
        if not idx.exists():
            warn(f"{d.name}: no _index.md")
            continue
        fm, body = front_matter(idx)
        name = (fm.get("title") or "").strip()
        if not name or d.name == "admin":
            continue  # 'admin' is the lab-description pseudo-author, not a person

        groups = [g for g in (fm.get("user_groups") or []) if g]
        section = GROUP_OF.get(groups[0] if groups else "", "alumni")
        role = (fm.get("role") or "").strip()

        # Current members: split by degree; alumni: `role` holds current position.
        if section == "current":
            rl = role.lower()
            if "phd" in rl or "ph.d" in rl:
                section = "phd"
            elif "visiting" in rl:
                section = "visiting"
            elif "undergrad" in rl:
                section = "undergrad"
            else:
                section = "ms"

        social = {}
        for s in fm.get("social") or []:
            icon = (s.get("icon") or "").strip()
            link = (s.get("link") or "").strip()
            if not link:
                continue
            # Six profiles are missing the mailto: scheme -> broken relative link.
            if icon == "envelope" and "@" in link and not link.startswith("mailto:"):
                warn(f"{name}: email link missing 'mailto:' -> fixed ({link})")
                link = "mailto:" + link
            social[icon] = link

        slug = slugify(name)
        photo = ""
        for cand in sorted(d.glob("[Aa]vatar.*")):
            photo = f"img/people/{slug}{cand.suffix.lower()}"
            resize(cand, IMG_PEOPLE / f"{slug}{cand.suffix.lower()}", 500)
            break
        else:
            warn(f"{name}: no avatar")

        out.append({
            "name": name,
            "slug": slug,
            "section": section,
            "role": role,
            "site": fix_url(fm.get("site") or "", name),
            "bio": (fm.get("bio") or "").strip(),
            "photo": photo,
            "social": social,
            "degree": "",
            "year": "",
            "now": "",
        })

    # Merge in graduation year / current position from Alumni.md.
    alumni_md = parse_alumni_md(src_root / "content/people/Alumni.md")
    index = {slugify(p["name"]): p for p in out}
    # also index on a looser key, since Alumni.md drops nicknames
    loose = {slugify(re.sub(r"\([^)]*\)", "", p["name"])): p for p in out}
    matched = 0
    for a in alumni_md:
        key = slugify(a["name"])
        p = index.get(key) or loose.get(slugify(re.sub(r"\([^)]*\)", "", a["name"])))
        if p:
            p.update({k: a[k] for k in ("degree", "year", "now") if a[k]})
            if a["site"] and not p["site"]:
                p["site"] = a["site"]
            matched += 1
        else:
            # Alumni with no profile folder -- keep them as text-only entries.
            out.append({
                "name": a["name"], "slug": slugify(a["name"]), "section": "alumni",
                "role": "", "site": a["site"], "bio": "", "photo": "", "social": {},
                "degree": a["degree"], "year": a["year"], "now": a["now"],
            })
    print(f"Alumni.md: {len(alumni_md)} entries, {matched} matched to a profile, "
          f"{len(alumni_md) - matched} added as text-only")
    return out


def extract_pubs(src_root):
    out = []
    for d in sorted((src_root / "content/publication").iterdir()):
        if not d.is_dir():
            continue
        idx = d / "index.md"
        if not idx.exists():
            continue
        fm, body = front_matter(idx)
        title = (fm.get("title") or "").strip()
        if not title:
            warn(f"{d.name}: no title")
            continue

        date = str(fm.get("date") or "")
        year = date[:4] if date[:4].isdigit() else ""
        types = [str(t) for t in (fm.get("publication_types") or [])]
        kind = PUB_KIND.get(types[0] if types else "", "other")

        links = []
        for key, label in [("url_pdf", "PDF"), ("url_code", "Code"),
                           ("url_video", "Video"), ("url_slides", "Slides"),
                           ("url_source", "Source"), ("url_poster", "Poster"),
                           ("url_project", "Project")]:
            u = (fm.get(key) or "").strip()
            if not u:
                continue
            # Locally hosted PDFs: copy out of the content tree, rewrite the URL.
            if u.startswith("/publication/"):
                rel = u[len("/publication/"):]
                srcf = src_root / "content/publication" / rel
                if srcf.exists():
                    dst = FILES / rel
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(srcf, dst)
                    u = f"files/{rel}"
                else:
                    warn(f"{d.name}: {key} points at missing file {u}")
                    # Try to find the PDF elsewhere in the tree.
                    hits = list((src_root / "content/publication").glob(f"*/{Path(rel).name}"))
                    if len(hits) == 1:
                        fixed = hits[0].relative_to(src_root / "content/publication")
                        dst = FILES / fixed
                        dst.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(hits[0], dst)
                        u = f"files/{fixed}"
                        warn(f"{d.name}:   -> recovered from {fixed}")
                    else:
                        continue
            links.append({"label": label, "url": u})

        for extra in fm.get("links") or []:
            if isinstance(extra, dict) and extra.get("url"):
                links.append({"label": (extra.get("name") or "Link").strip(),
                              "url": extra["url"].strip()})

        thumb = ""
        for cand in sorted(d.glob("featured.*")):
            if cand.suffix.lower() in {".jpg", ".jpeg", ".png", ".gif", ".webp"}:
                thumb = f"img/pubs/{d.name}{cand.suffix.lower()}"
                resize(cand, IMG_PUBS / f"{d.name}{cand.suffix.lower()}", 800)
                break

        out.append({
            "id": d.name,
            "title": title,
            "authors": [str(a).strip() for a in (fm.get("authors") or [])],
            "year": year,
            "date": date,
            "venue": clean_venue(fm.get("publication_short"), fm.get("publication")),
            "venue_full": (fm.get("publication") or "").replace("*", "").strip(),
            "kind": kind,
            "abstract": (fm.get("abstract") or "").strip(),
            "thumb": thumb,
            "links": links,
        })

    out.sort(key=lambda p: (p["date"], p["title"]), reverse=True)
    return out


def main():
    src_root = Path(sys.argv[1] if len(sys.argv) > 1
                    else "/Users/bocehu/codes/helping_hands_website").resolve()
    if not (src_root / "content").is_dir():
        sys.exit(f"no content/ under {src_root}")

    DATA.mkdir(exist_ok=True)
    people = extract_people(src_root)
    pubs = extract_pubs(src_root)

    (DATA / "people.json").write_text(
        json.dumps(people, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (DATA / "publications.json").write_text(
        json.dumps(pubs, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    by_section = {}
    for p in people:
        by_section[p["section"]] = by_section.get(p["section"], 0) + 1
    print(f"people:       {len(people)}  {by_section}")
    print(f"publications: {len(pubs)}  with thumb: {sum(1 for p in pubs if p['thumb'])}"
          f"  total links: {sum(len(p['links']) for p in pubs)}")
    if warnings:
        print(f"\n{len(warnings)} warning(s):")
        for w in warnings:
            print("  -", w)


if __name__ == "__main__":
    main()
