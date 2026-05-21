#!/usr/bin/env python3
"""
Sync the Now page on the personal site from Obsidian.

Reads:  Claude Memory/Current Focus.md
Writes: index.html (between <!--SYNC:ACTIVE-->...<!--/SYNC:ACTIVE--> markers etc.)

Then commits + pushes to GitHub Pages if anything changed.

Usage:
    python3 sync-now.py            # sync and push
    python3 sync-now.py --dry-run  # show what would change, don't write
"""

import re
import subprocess
import sys
from datetime import date
from pathlib import Path

VAULT = Path("/Users/enzoabuliak/Library/Mobile Documents/iCloud~md~obsidian/Documents/Enzo's Mac Vault")
FOCUS = VAULT / "Claude Memory" / "Current Focus.md"
SITE = Path("/Users/enzoabuliak/Documents/personal-site")
HTML = SITE / "index.html"

# ── Status keyword → badge class ──────────────────────────────────
STATUS_KEYWORDS = [
    (r"\boverdue\b",          "badge-red",    "Overdue"),
    (r"\bdue\s+([A-Z][a-z]+\s+\d+)", "badge-yellow", None),   # captures date
    (r"\bin production\b",    "badge-green",  "In production"),
    (r"\bin progress\b",      "badge-green",  "In progress"),
    (r"\b(submitted|done|complete)\b", "badge-blue", "Done"),
    (r"\bdaily\b",            "badge-green",  "Daily"),
]

DRY = "--dry-run" in sys.argv


SECTION_END = re.compile(r"\n(?=##\s|---\s*$)", re.M)


def grab_section(md: str, heading: str):
    """Return the body text under a `## Heading` until the next ## or ---."""
    m = re.search(rf"##\s+{re.escape(heading)}\s*\n(.+?)(?=\n##\s|\n---\s*\n|\Z)", md, re.S)
    return m.group(1).strip() if m else ""


def parse_focus(md: str):
    active   = parse_numbered_list(grab_section(md, "This Week's Priorities"))
    upcoming = parse_bullet_list(grab_section(md, "Coming Up"))
    return active, upcoming


def parse_numbered_list(block: str):
    items = []
    chunks = re.split(r"\n(?=\d+\.\s)", block.strip())
    for chunk in chunks:
        c = chunk.strip()
        if not re.match(r"^\d+\.", c):
            continue
        c = re.sub(r"^\d+\.\s*", "", c)
        items.append(parse_entry(c, multiline=True))
    return items


def parse_bullet_list(block: str):
    items = []
    for line in block.strip().split("\n"):
        line = line.strip()
        if not line.startswith("-"):
            continue
        items.append(parse_entry(line.lstrip("- ").strip(), multiline=False))
    return items


def strip_emoji(s: str) -> str:
    return re.sub(r"[\U0001F000-\U0001FFFF☀-➿️]", "", s).strip()


def parse_entry(raw: str, multiline: bool):
    """
    Numbered (multiline=True) format:
        **Title — optional status**  ← first line, bolded
           Body paragraph here.       ← indented continuation
    Bullet (multiline=False) format:
        **Title** — body text         ← single line
    """
    raw = raw.strip()
    lines = raw.split("\n")
    first = lines[0].strip()

    # Pull bolded chunk
    m = re.match(r"\*\*(.+?)\*\*", first)
    if m:
        head = m.group(1).strip()
        remainder_first = first[m.end():].strip(" —–-:")
    else:
        head = first
        remainder_first = ""

    # head may contain "Title — status"
    if " — " in head:
        title, status_text = head.split(" — ", 1)
    elif " - " in head and not multiline:
        title, status_text = head.split(" - ", 1)
    else:
        title, status_text = head, ""

    title = strip_emoji(title).strip()
    status_text = strip_emoji(status_text).strip()

    # Body
    if multiline and len(lines) > 1:
        body = " ".join(l.strip() for l in lines[1:] if l.strip() and not l.strip().startswith("-"))
    else:
        body = remainder_first
    body = strip_emoji(body).strip(" —–-")
    # Truncate to first sentence-ish if very long
    if len(body) > 220:
        cut = body[:220].rsplit(".", 1)
        body = cut[0] + "." if len(cut) > 1 else body[:220] + "…"

    badge = detect_badge(status_text or body)
    return {"title": title, "body": body, "badge": badge, "tag": ""}


def detect_badge(text: str):
    t = text.lower()
    for pat, cls, label in STATUS_KEYWORDS:
        m = re.search(pat, t)
        if m:
            if label is None:
                # "due X" pattern
                return {"cls": cls, "label": f"Due {m.group(1).title()}"}
            return {"cls": cls, "label": label}
    return None


def extract_tag(text: str):
    """Look for a #hashtag or trailing tag like 'Film · Director'.
    Fallback: empty."""
    m = re.search(r"#(\w+)", text)
    if m:
        return m.group(1).capitalize()
    return ""


def render_item(item):
    title = html_escape(item["title"])
    body = html_escape(item["body"]) or "—"
    badge_html = ""
    if item["badge"]:
        badge_html = (
            f'\n            <span class="badge {item["badge"]["cls"]}">'
            f'{html_escape(item["badge"]["label"])}</span>'
        )
    tag_html = ""
    if item["tag"]:
        tag_html = f'\n          <div class="now-item-tag">{html_escape(item["tag"])}</div>'

    top = (
        f'<div class="now-item-top">\n'
        f'              <span class="now-item-title">{title}</span>{badge_html}\n'
        f'            </div>'
    ) if badge_html else (
        f'<span class="now-item-title">{title}</span>'
    )

    return (
        f'          <div class="now-item">\n'
        f'            {top}\n'
        f'            <div class="now-item-body">{body}</div>'
        f'{tag_html}\n'
        f'          </div>'
    )


def html_escape(s: str):
    return (s.replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")
             .replace('"',"&quot;"))


def replace_block(html: str, marker: str, new_content: str):
    pattern = re.compile(
        rf"(<!--SYNC:{marker}-->)(.*?)(<!--/SYNC:{marker}-->)", re.S
    )
    return pattern.sub(lambda m: f"{m.group(1)}\n{new_content}\n{m.group(3)}", html)


def main():
    if not FOCUS.exists():
        print(f"❌ Not found: {FOCUS}")
        sys.exit(1)
    if not HTML.exists():
        print(f"❌ Not found: {HTML}")
        sys.exit(1)

    md = FOCUS.read_text(encoding="utf-8")
    active, upcoming = parse_focus(md)

    print(f"→ Parsed {len(active)} active, {len(upcoming)} upcoming entries")

    active_html = "\n\n".join(render_item(i) for i in active) if active else ""
    upcoming_html = "\n\n".join(render_item(i) for i in upcoming) if upcoming else ""

    html = HTML.read_text(encoding="utf-8")
    new = replace_block(html, "ACTIVE", active_html)
    new = replace_block(new, "UPCOMING", upcoming_html)

    # Date
    today = date.today().isoformat()
    new = re.sub(
        r"(<!--SYNC:DATE-->).*?(<!--/SYNC:DATE-->)",
        rf"\g<1>{today}\g<2>",
        new,
    )

    if new == html:
        print("✓ No changes")
        return

    if DRY:
        print("--- DRY RUN, would write changes ---")
        return

    HTML.write_text(new, encoding="utf-8")
    print(f"✓ Updated {HTML.name}")

    # Commit + push
    subprocess.run(["git", "add", "index.html"], cwd=SITE, check=True)
    r = subprocess.run(
        ["git", "diff", "--cached", "--quiet"], cwd=SITE
    )
    if r.returncode == 0:
        print("✓ Nothing to commit")
        return
    subprocess.run(
        ["git", "-c", "user.email=enzo.abuliak@gmail.com",
                "-c", "user.name=Enzo Abuliak",
         "commit", "-m", f"Sync Now page — {today}"],
        cwd=SITE, check=True,
    )
    subprocess.run(["git", "push"], cwd=SITE, check=True)
    print("✓ Pushed to GitHub Pages")


if __name__ == "__main__":
    main()
