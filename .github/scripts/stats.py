"""Fetch GitHub stats (repos, contributed, stars, commits, followers, lines of code)
and write them into the "GitHub Stats" lines of dark_mode.svg and light_mode.svg.

With ACCESS_TOKEN (a personal access token that can read your repositories) it uses
the GraphQL API and also counts private repositories the token can read.
Without it, it falls back to the public REST API (GITHUB_TOKEN only raises rate limits).
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
PRIVATE_TOKEN = os.environ.get("ACCESS_TOKEN")
TOKEN = PRIVATE_TOKEN or os.environ.get("GITHUB_TOKEN")
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


def graphql(query, variables):
    """POST a GraphQL query. Partial errors (e.g. a repo the token cannot read) are
    logged and the data that did come back is returned."""
    body = json.dumps({"query": query, "variables": variables}).encode()
    headers = {"User-Agent": "profile-stats", "Authorization": f"Bearer {PRIVATE_TOKEN}",
               "Content-Type": "application/json"}
    for attempt in range(5):
        try:
            req = urllib.request.Request("https://api.github.com/graphql", data=body, headers=headers)
            with urllib.request.urlopen(req, timeout=60) as r:
                data = json.load(r)
        except urllib.error.HTTPError as e:
            if e.code in (502, 503, 504, 403, 429) and attempt < 4:
                print(f"graphql {e.code}, retrying")
                time.sleep(5 * (attempt + 1))
                continue
            raise
        if data.get("errors"):
            # Actions logs are public on a public repo: never print messages that may
            # contain private repository names.
            print(f"graphql: {len(data['errors'])} item(s) not readable with this token, skipped")
        if not data.get("data"):
            raise RuntimeError("graphql returned no data")
        return data["data"]
    raise RuntimeError("graphql: giving up")


REPOS_QUERY = """
query($login: String!, $id: ID!, $after: String) {
  user(login: $login) {
    repositories(first: 50, after: $after,
                 ownerAffiliations: [OWNER, COLLABORATOR, ORGANIZATION_MEMBER]) {
      pageInfo { hasNextPage endCursor }
      nodes {
        nameWithOwner isFork stargazerCount
        owner { login }
        defaultBranchRef { target { ... on Commit { history(author: {id: $id}) { totalCount } } } }
      }
    }
  }
}"""

HISTORY_QUERY = """
query($owner: String!, $name: String!, $id: ID!, $after: String) {
  repository(owner: $owner, name: $name) {
    defaultBranchRef { target { ... on Commit {
      history(first: 100, after: $after, author: {id: $id}) {
        pageInfo { hasNextPage endCursor }
        nodes { additions deletions }
      }
    } } }
  }
}"""


def _history(node):
    return (((node or {}).get("defaultBranchRef") or {}).get("target") or {}).get("history") or {}


def fetch_with_private():
    """Every repository the token can read (own, collaborator, organization), private included."""
    me = graphql("query($l: String!) { user(login: $l) { id followers { totalCount } } }", {"l": USER})["user"]
    uid = me["id"]

    repos, after = [], None
    while True:
        page = graphql(REPOS_QUERY, {"login": USER, "id": uid, "after": after})["user"]["repositories"]
        repos += [r for r in page["nodes"] if r]
        if not page["pageInfo"]["hasNextPage"]:
            break
        after = page["pageInfo"]["endCursor"]

    owned = [r for r in repos if r["owner"]["login"].lower() == USER.lower()]
    contributed = [r for r in repos if _history(r).get("totalCount", 0) > 0]

    add = dele = 0
    for r in contributed:
        if r["isFork"]:
            continue
        owner, name = r["nameWithOwner"].split("/", 1)
        after = None
        while True:
            data = graphql(HISTORY_QUERY, {"owner": owner, "name": name, "id": uid, "after": after})
            history = _history(data.get("repository"))
            nodes = [n for n in history.get("nodes") or [] if n]
            add += sum(n["additions"] for n in nodes)
            dele += sum(n["deletions"] for n in nodes)
            page_info = history.get("pageInfo") or {}
            if not page_info.get("hasNextPage"):
                break
            after = page_info["endCursor"]

    return {
        "repos": len(owned), "contributed": len(contributed),
        "stars": sum(r["stargazerCount"] for r in owned),
        "commits": sum(_history(r)["totalCount"] for r in contributed),
        "followers": me["followers"]["totalCount"],
        "loc": add - dele, "loc_add": add, "loc_del": dele,
    }


def fetch():
    if PRIVATE_TOKEN:
        print("ACCESS_TOKEN set: counting private repositories too")
        return fetch_with_private()
    print("no ACCESS_TOKEN: counting public repositories only")
    return fetch_public()


def fetch_public():
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
