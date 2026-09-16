# The Helping Hands Lab — website (v2)

A static site with no framework, no theme, and no dependencies. `build.py` uses
only the Python standard library, so there is nothing to install and nothing
that can rot.

```
data/          the content — this is the only place most edits happen
  site.json          nav, homepage copy, code repos, videos, openings
  people.json        everyone in the lab, past and present
  publications.json  58 papers
templates/
  base.html          the page shell (header, nav, footer)
static/        copied verbatim into public/
  css/style.css      all styling; every knob lives in :root at the top
  img/people/        portraits, pre-resized to 500px
  img/pubs/          paper thumbnails, pre-resized to 800px
  files/             locally hosted PDFs
build.py       generates public/
tools/extract.py  one-time migration from the old Hugo site (not part of the build)
```

## Build and preview

```bash
python3 build.py            # -> public/
python3 build.py --serve    # -> public/, then http://localhost:8000
```

`public/` uses only relative paths, so you can also just open
`public/index.html` in a browser, and the same output works at the root of a
domain or under a subdirectory like `/research/helpinghands/`.

## Adding yourself to the lab page

Add an entry to `data/people.json` and drop a square-ish photo in
`static/img/people/`:

```json
{
  "name": "Your Name",
  "slug": "your-name",
  "section": "phd",
  "start": "2027-09",
  "role": "PhD student, CS",
  "site": "https://your-homepage.example",
  "photo": "img/people/your-name.jpg",
  "social": { "envelope": "mailto:you@northeastern.edu",
              "google-scholar": "https://scholar.google.com/..." }
}
```

**Append it anywhere in the file — order in the JSON does not matter.** Each
section is sorted at build time.

`section` is one of `faculty`, `phd`, `ms`, `visiting`, `undergrad`,
`phd_alumni`, `alumni`. Alumni entries may also carry `degree`, `year` and
`now` (current position), which is what the Alumni list shows.

`start` is when the person joined, `"YYYY"` or `"YYYY-MM"`.

### How each section is ordered

`people_sections` in `data/site.json` sets the order per section:

| `sort`    | meaning                        |
|-----------|--------------------------------|
| `-start`  | most recently joined first     |
| `start`   | longest-serving first          |
| `name`    | by surname, A–Z                |
| `-year`   | most recent graduate first     |

Ties always fall back to surname. To flip a section, change that one word — for
example, listing senior PhD students first is `"sort": "start"`.

A section sorted by `start` requires every member to have one: forget it, or
write it as `Sept 2026`, and the build fails naming the person, so nobody
quietly ends up in the wrong place.

Resize the photo first so the repo stays small:

```bash
sips --resampleHeightWidthMax 500 photo.jpg --out static/img/people/your-name.jpg
```

## Adding a paper

Add an entry to the top of `data/publications.json` and a thumbnail to
`static/img/pubs/`:

```json
{
  "id": "short_slug",
  "title": "Paper Title",
  "authors": ["First Author", "Second Author"],
  "date": "2026-05-01",
  "year": "2026",
  "venue": "CoRL 2026",
  "thumb": "img/pubs/short_slug.jpg",
  "links": [{ "label": "PDF", "url": "https://arxiv.org/abs/..." },
            { "label": "Code", "url": "https://github.com/..." }]
}
```

Papers are shown newest first by `date`. Author names that match someone in
`people.json` are bolded automatically — no need to mark them up.

## Why JSON instead of the old Markdown front matter

`build.py` validates the data before writing anything: a missing field, a
malformed link or a photo path that does not exist fails the build with a line
number, and the deploy step never runs. The old Hugo site had the same safety
property; plain hand-written HTML would not.

## Deployment

Unchanged from the old site in every respect except the build command. The
GitHub Action builds, wipes the target directory on the Khoury server and
copies `public/` up over scp:

```yaml
- run: python3 build.py          # replaces: hugo --minify -b ...
```

No `-b`/baseURL flag is needed because every path in the output is relative.

## Changing the design

Nearly everything visual is in the `:root` block at the top of
`static/css/style.css` — column width, colors, the accent red, fonts, spacing.
Page structure lives in the `page_*` functions in `build.py`.
