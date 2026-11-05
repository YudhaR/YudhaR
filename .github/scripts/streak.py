"""Build streak.svg from the public GitHub contribution calendar (no token needed)."""
import datetime as dt
import re
import sys
import time
import urllib.error
import urllib.request
from xml.sax.saxutils import escape

USER = sys.argv[1] if len(sys.argv) > 1 else "YudhaR"
START_YEAR = 2022
TZ = dt.timezone(dt.timedelta(hours=7))  # Asia/Jakarta
OUT = "streak.svg"
EXCLUDE_WEEKDAYS = {5, 6}  # Saturday, Sunday: empty days here don't break the streak

C = {
    "bg": "#1a1b27", "stroke": "#e4e2e2", "ring": "#7aa2f7", "fire": "#bb9af7",
    "num": "#70a5fd", "label": "#7aa2f7", "date": "#38bdae", "sep": "#e4e2e2",
    "current": "#bb9af7",
}


def fetch_year(year):
    url = f"https://github.com/users/{USER}/contributions?from={year}-01-01&to={year}-12-31"
    req = urllib.request.Request(url, headers={"User-Agent": "streak-card"})
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                html = r.read().decode("utf-8")
            break
        except (urllib.error.HTTPError, urllib.error.URLError) as e:
            if attempt == 3:
                raise
            print(f"{year}: {e}, retrying")
            time.sleep(5 * (attempt + 1))
    dates = dict(re.findall(r'data-date="(\d{4}-\d{2}-\d{2})" id="([^"]+)"', html))
    dates = {v: k for k, v in dates.items()}
    counts = {}
    for cell_id, text in re.findall(r'<tool-tip[^>]*for="([^"]+)"[^>]*>([^<]*)</tool-tip>', html):
        if cell_id in dates:
            m = re.match(r"(\d+) contribution", text)
            counts[dates[cell_id]] = int(m.group(1)) if m else 0
    return counts


def collect():
    today = dt.datetime.now(TZ).date()
    days = {}
    for year in range(START_YEAR, today.year + 1):
        days.update(fetch_year(year))
    return {dt.date.fromisoformat(k): v for k, v in days.items() if dt.date.fromisoformat(k) <= today}, today


def streaks(days, today):
    ordered = sorted(days)
    total = sum(days.values())
    first = next((d for d in ordered if days[d] > 0), ordered[0])

    # An empty excluded day (weekend) neither breaks nor extends a streak;
    # contributions made on it still count.
    skippable = lambda d: d.weekday() in EXCLUDE_WEEKDAYS

    longest = (0, None, None)
    run, run_start = 0, None
    for d in ordered:
        if days[d] > 0:
            run_start = run_start or d
            run += 1
            if run > longest[0]:
                longest = (run, run_start, d)
        elif not skippable(d):
            run, run_start = 0, None

    # walk back from today; an empty today does not break the streak yet
    current, current_start, current_end = 0, None, None
    cursor = today
    while cursor >= ordered[0]:
        if days.get(cursor, 0) > 0:
            current += 1
            current_start = cursor
            current_end = current_end or cursor
        elif not (cursor == today or skippable(cursor)):
            break
        cursor -= dt.timedelta(days=1)
    return total, first, current, current_start, current_end, longest


def fmt(d, with_year=True):
    if d is None:
        return ""
    s = d.strftime("%b %-d")
    return f"{s}, {d.year}" if with_year else s


def render(total, first, current, cs, ce, longest):
    today = dt.datetime.now(TZ).date()
    same_year = lambda a, b: a and b and a.year == b.year == today.year
    cur_range = "" if current == 0 else (
        f"{fmt(cs, not same_year(cs, ce))} - {fmt(ce, not same_year(cs, ce))}" if cs != ce else fmt(ce, ce.year != today.year))
    lng, ls, le = longest
    lng_range = "" if lng == 0 else (f"{fmt(ls)} - {fmt(le)}" if ls != le else fmt(ls))

    t = lambda x, y, txt, size, color, weight=400, delay=0: (
        f'<text x="{x}" y="{y}" text-anchor="middle" class="fade" style="animation-delay:{delay}s" '
        f'fill="{color}" font-size="{size}" font-weight="{weight}">{escape(txt)}</text>')

    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="495" height="195" viewBox="0 0 495 195" role="img" aria-label="GitHub streak for {USER}">
<style>
text{{font-family:"Segoe UI",Ubuntu,"Helvetica Neue",Sans-Serif}}
.fade{{opacity:0;animation:fade .6s ease-in-out forwards}}
.ring{{stroke-dasharray:252;stroke-dashoffset:252;animation:draw 1s ease-out .3s forwards}}
@keyframes fade{{to{{opacity:1}}}}
@keyframes draw{{to{{stroke-dashoffset:0}}}}
@media (prefers-reduced-motion:reduce){{.fade{{animation:none;opacity:1}}.ring{{animation:none;stroke-dashoffset:0}}}}
</style>
<rect width="495" height="195" rx="10" fill="{C["bg"]}"/>
<line x1="165" y1="28" x2="165" y2="170" stroke="{C["sep"]}" stroke-width="1" opacity=".6"/>
<line x1="330" y1="28" x2="330" y2="170" stroke="{C["sep"]}" stroke-width="1" opacity=".6"/>
{t(82.5, 79, f"{total:,}", 28, C["num"], 700, .6)}
{t(82.5, 114, "Total Contributions", 14, C["label"], 400, .7)}
{t(82.5, 145, f"{fmt(first)} - Present", 12, C["date"], 400, .8)}
<circle cx="247.5" cy="71" r="40" fill="none" stroke="{C["ring"]}" stroke-width="5" class="ring" transform="rotate(-90 247.5 71)"/>
<rect x="235" y="22" width="25" height="22" fill="{C["bg"]}"/>
<path class="fade" style="animation-delay:.5s" fill="{C["fire"]}" transform="translate(237.5 19.5)" d="M10.4 0C10.4 4 6 6.2 6 10.5c0 2 1.3 3.7 3 4.4-.4-1-.2-2.6 1.2-3.9 1.6 1.4 2.4 2.8 2.1 4.1 1.9-.6 3.4-2.4 3.4-4.6 0-3.6-2.8-5.4-3.4-8.6-.5 1.4-1.3 2.4-2.4 3.1.6-1.6.8-3.4.5-5z"/>
{t(247.5, 81, str(current), 28, C["current"], 700, .6)}
{t(247.5, 140, "Current Streak", 14, C["current"], 700, .9)}
{t(247.5, 162, cur_range, 12, C["date"], 400, .9)}
{t(412.5, 79, str(lng), 28, C["num"], 700, 1.2)}
{t(412.5, 114, "Longest Streak", 14, C["label"], 400, 1.3)}
{t(412.5, 145, lng_range, 12, C["date"], 400, 1.4)}
</svg>
'''


def main():
    days, today = collect()
    if not days:
        sys.exit("no contribution data found")
    stats = streaks(days, today)
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(render(*stats))
    total, first, current, cs, ce, longest = stats
    print(f"total={total} first={first} current={current} ({cs}..{ce}) longest={longest[0]} ({longest[1]}..{longest[2]})")


if __name__ == "__main__":
    main()
