#!/usr/bin/env python3
"""Auto-write docs/CHANGE_LOG.md entries for commits that did not add one themselves.

Run by .github/workflows/changelog.yml on every push to main, so the log is filled for
EVERYONE (owner, Claude, contractors) whether or not they know the log exists.

Authors can make entries richer with single-line trailers in the commit message:
    Area: api | Before: ... | Problem: ... | Action: ... | After: ...   (one per line)
Missing fields are written as "not provided" - never invented.

Usage: changelog_auto.py --before <sha> --after <sha> [--file docs/CHANGE_LOG.md] [--max 30]
"""
import argparse, datetime as dt, re, subprocess, sys

MARKER = "<!-- AUTO-ENTRIES-BELOW (newest first) -->"
NOT_GIVEN = "_not provided by the author_"
TRAILER = re.compile(r"^(Area|Before|Problem|Action|After):\s*(.+)$", re.I | re.M)
ZERO = "0" * 40
AREAS = [  # first matching prefix wins per file
    ("apps/api/alembic", "db"), ("apps/api/melorin", "api"), ("apps/api/tests", "tests"),
    ("apps/api", "api"), ("apps/admin-web", "admin-web"), ("apps/store-web", "store-web"),
    ("apps/telegram", "bot"), ("packages", "shared"), ("infra", "infra"),
    ("docker-compose", "infra"), (".github", "ci-deploy"), ("scripts", "scripts"),
    ("docs", "docs"), (".env", "config"),
]


def git(*a):
    return subprocess.run(["git", *a], check=True, capture_output=True, text=True).stdout


def areas_for(files):
    out = []
    for f in files:
        for prefix, name in AREAS:
            if f.startswith(prefix):
                if name not in out:
                    out.append(name)
                break
        else:
            if "other" not in out:
                out.append("other")
    return out[:3] or ["other"]


def one_line(s, n=300):
    s = re.sub(r"\s+", " ", s).strip()
    return s if len(s) <= n else s[: n - 1] + "…"


def entry_for(sha, logfile):
    fmt = git("show", "-s", "--format=%an%x1f%ae%x1f%cI%x1f%B", sha).rstrip("\n").split("\x1f", 3)
    name, email, when, message = (fmt + [""] * 4)[:4]
    subject, _, body = message.partition("\n")  # raw message: keeps line breaks, unlike %s
    files = [f for f in git("show", "--name-only", "--format=", sha).split("\n") if f]
    if not files or logfile in files:
        return None  # empty/merge commit, or the author already wrote an entry
    if "[skip changelog]" in (subject + body).lower() or "github-actions[bot]" in (name + email):
        return None
    # trailers may be anywhere in the message, including the first line
    tr = {k.lower(): one_line(v) for k, v in TRAILER.findall(subject + "\n" + body)}
    rest = one_line(TRAILER.sub("", body), 400)
    if TRAILER.match(subject):
        subject = "commit without a title"
    ts = dt.datetime.fromisoformat(when).astimezone(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    area = tr.get("area") or ", ".join(areas_for(files))
    shown = ", ".join(f"`{f}`" for f in files[:8]) + (f" (+{len(files) - 8} more)" if len(files) > 8 else "")
    action = tr.get("action") or one_line(subject + (f" - {rest}" if rest else ""))
    return (
        f"### {ts} - {name} - {area}  _(auto)_\n"
        f"- **Before:** {tr.get('before', NOT_GIVEN)}\n"
        f"- **Problem:** {tr.get('problem', NOT_GIVEN)}\n"
        f"- **Action:** {action}\n"
        f"- **After:** {tr.get('after', NOT_GIVEN + ' (see CI/Actions result for this commit)')}\n"
        f"- **Files ({len(files)}):** {shown}\n"
        f"- **Ref:** `{sha[:7]}`\n"
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--before", required=True)
    ap.add_argument("--after", required=True)
    ap.add_argument("--file", default="docs/CHANGE_LOG.md")
    ap.add_argument("--max", type=int, default=30)
    a = ap.parse_args()

    rng = f"{a.after}~1..{a.after}" if a.before in ("", ZERO) else f"{a.before}..{a.after}"
    shas = git("rev-list", "--reverse", "--no-merges", rng).split()[-a.max:]
    text = open(a.file, encoding="utf-8").read()
    new = []
    for sha in shas:
        if f"`{sha[:7]}`" in text:
            continue  # already logged
        e = entry_for(sha, a.file)
        if e:
            new.append(e)
    if not new:
        print("changelog_auto: nothing to add")
        return 0
    block = "\n".join(reversed(new)) + "\n"  # newest first
    if MARKER in text:
        text = text.replace(MARKER, MARKER + "\n\n" + block.rstrip("\n") + "\n", 1)
    else:
        i = text.index("\n---\n") + 5
        text = text[:i] + "\n" + MARKER + "\n\n" + block + text[i:]
    open(a.file, "w", encoding="utf-8").write(text)
    print(f"changelog_auto: added {len(new)} entr{'y' if len(new) == 1 else 'ies'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
