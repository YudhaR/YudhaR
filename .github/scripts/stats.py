"""Fetch GitHub stats (repos, contributed, stars, commits, followers, lines of code)
and write them into the "GitHub Stats" lines of dark_mode.svg and light_mode.svg.

Uses the public REST API. Set GITHUB_TOKEN (or ACCESS_TOKEN) for higher rate limits.
Only public repositories and commits are counted.
"""
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from xml.sax.saxutils import escape

USER = os.environ.get("USER_NAME") or (sys.argv[1] if len(sys.argv) > 1 else "YudhaR")
TOKEN = os.environ.get("ACCESS_TOKEN") or os.environ.get("GITHUB_TOKEN")
SVG_FILES = ["dark_mode.svg", "light_mode.svg"]

LINE_CHARS = 76   # must match generate_profile.py
LEFT_COL = 46     # where the second column (Stars / Followers) starts


def api(path, accept="application/vnd.github+json"):
    url = path if path.startswith("http") else f"https://api.github.com{path}"
    headers = {"User-Agent": "profile-stats", "Accept": accept}
    if TOKEN:
        headers["Authorization"] = f"Bearer {TOKEN}"
    for attempt in range(4):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=30) as r:
                body = r.read()
                return r.status, (json.loads(body) if body else None)
        except urllib.error.HTTPError as e:
            if e.code in (403, 429) and attempt < 3:
                wait = int(e.headers.get("Retry-After") or 0) or 30
                print(f"rate limited on {path}, waiting {wait}s")
                time.sleep(wait)
                continue
            raise
    raise RuntimeError(f"giving up on {path}")


def search_commits():
    total, repos, page = 0, set(), 1
    while True:
        _, data = api(f"/search/commits?q=author:{USER}&per_page=100&page={page}")
        total = data["total_count"]
        repos.update(item["repository"]["full_name"] for item in data["items"])
        if page * 100 >= min(total, 1000) or not data["items"]:
            return total, repos
        page += 1
        time.sleep(2)  # search API allows few requests per minute


def lines_of_code(repo_names):
    """Sum additions/deletions by USER. GitHub answers 202 while it computes a repo's
    stats, so pending repos are retried in a few passes instead of one by one."""
    add = dele = 0
    pending = sorted(repo_names)
    for attempt in range(4):
        waiting = []
        for name in pending:
            status, data = api(f"/repos/{name}/stats/contributors")
            if status == 202:
                waiting.append(name)
                continue
            for contributor in data or []:
                author = contributor.get("author") or {}
                if author.get("login", "").lower() == USER.lower():
                    add += sum(w["a"] for w in contributor["weeks"])
                    dele += sum(w["d"] for w in contributor["weeks"])
        if not waiting:
            break
        pending = waiting
        time.sleep(10 + attempt * 10)
    else:
        print(f"stats not ready, skipped: {', '.join(pending)}")
    return add, dele


def fetch():
    _, user = api(f"/users/{USER}")
    _, repos = api(f"/users/{USER}/repos?per_page=100&type=owner")
    stars = sum(r["stargazers_count"] for r in repos)
    commits, contributed = search_commits()
    loc_repos = contributed | {r["full_name"] for r in repos if not r["fork"]}
    add, dele = lines_of_code(loc_repos)
    return {
        "repos": user["public_repos"], "contributed": len(contributed), "stars": stars,
        "commits": commits, "followers": user["followers"],
        "loc": add - dele, "loc_add": add, "loc_del": dele,
    }


def _dots(used, width):
    return "." * max(2, width - used - 1) + " "


def stats_lines(s):
    """Return the three stats lines as lists of (css_class, text)."""
    n = lambda v: "-" if v is None else f"{v:,}"

    repos, contrib, stars = n(s["repos"]), n(s["contributed"]), n(s["stars"])
    left = len(". Repos: ") + len(repos) + len(" {Contributed: ") + len(contrib) + len("}")
    right = len(" | Stars: ") + len(stars)
    line1 = [
        ("label", ". Repos: "), ("dots", _dots(left, LEFT_COL)), ("value", repos),
        ("label", " {Contributed: "), ("value", contrib), ("label", "}"),
        ("label", " | Stars: "), ("dots", _dots(right, LINE_CHARS - LEFT_COL)), ("value", stars),
    ]

    commits, followers = n(s["commits"]), n(s["followers"])
    left = len(". Commits: ") + len(commits)
    right = len(" | Followers: ") + len(followers)
    line2 = [
        ("label", ". Commits: "), ("dots", _dots(left, LEFT_COL)), ("value", commits),
        ("label", " | Followers: "), ("dots", _dots(right, LINE_CHARS - LEFT_COL)), ("value", followers),
    ]

    loc, add, dele = n(s["loc"]), n(s["loc_add"]), n(s["loc_del"])
    tail = [("value", loc), ("label", " ( "), ("add", f"{add}++"), ("label", ", "),
            ("del", f"{dele}--"), ("label", " )")]
    head = ". Lines of Code on GitHub: "
    used = len(head) + sum(len(t) for _, t in tail)
    line3 = [("label", head), ("dots", _dots(used, LINE_CHARS))] + tail
    return [line1, line2, line3]


def spans(parts):
    return "".join(f'<tspan class="{cls}">{escape(txt)}</tspan>' for cls, txt in parts)


def apply(path, lines):
    with open(path, encoding="utf-8") as f:
        svg = f.read()
    for i, parts in enumerate(lines, 1):
        svg, count = re.subn(
            rf'(<text[^>]*id="gh-stats-{i}"[^>]*>).*?(</text>)',
            lambda m: m.group(1) + spans(parts) + m.group(2), svg, flags=re.S)
        if count != 1:
            sys.exit(f'{path}: element id="gh-stats-{i}" not found')
    with open(path, "w", encoding="utf-8") as f:
        f.write(svg)


def main():
    s = fetch()
    print(json.dumps(s))
    lines = stats_lines(s)
    for path in SVG_FILES:
        apply(path, lines)
        print(f"updated {path}")


if __name__ == "__main__":
    main()
