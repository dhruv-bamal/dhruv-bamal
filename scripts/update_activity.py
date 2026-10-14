#!/usr/bin/env python3
"""Render public GitHub statistics and weekly contributions; stdlib only.

Failure to read/validate GitHub data leaves the last successful output intact.
The optional GITHUB_TOKEN is sent only to api.github.com, never to HTML pages.
"""
import datetime as dt
from html import escape
from html.parser import HTMLParser
import json
import math
import os
from pathlib import Path
import re
import urllib.request

USER = 'dhruv-bamal'
ROOT = Path(__file__).resolve().parents[1]


def fetch(url):
    api = url.startswith('https://api.github.com/')
    headers = {'User-Agent': 'dhruv-bamal-profile', 'Accept': 'application/vnd.github+json' if api else 'text/html'}
    if api and os.environ.get('GITHUB_TOKEN'):
        headers['Authorization'] = 'Bearer ' + os.environ['GITHUB_TOKEN']
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=30) as response:
        return response.read().decode('utf-8')


class CalendarParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.cells, self.labels, self.tip = {}, {}, None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if 'data-date' in attrs and 'data-level' in attrs:
            self.cells[attrs['id']] = (dt.date.fromisoformat(attrs['data-date']), int(attrs['data-level']))
        if tag == 'tool-tip':
            self.tip = attrs.get('for')
            if self.tip:
                self.labels[self.tip] = ''

    def handle_data(self, data):
        if self.tip:
            self.labels[self.tip] += data

    def handle_endtag(self, tag):
        if tag == 'tool-tip':
            self.tip = None

    def days(self):
        result = []
        for cell_id, (day, level) in self.cells.items():
            label = self.labels.get(cell_id, '').strip()
            match = re.match(r'(No|[\d,]+) contributions?\b', label)
            if not match or not 0 <= level <= 4:
                raise ValueError('Unrecognized GitHub markup; preserving the last successful chart')
            count = 0 if match[1] == 'No' else int(match[1].replace(',', ''))
            result.append((day, level, count))
        result.sort()
        if len(result) < 365 or len({d[0] for d in result}) != len(result):
            raise ValueError('Incomplete or duplicate contribution data')
        result = result[-365:]
        if (result[-1][0] - result[0][0]).days != 364:
            raise ValueError('Contribution data has missing days')
        return result


def weekly_totals(days):
    """Monday-Sunday buckets. Keep and identify both partial edge weeks."""
    grouped = {}
    for date, _level, count in days:
        start = date - dt.timedelta(days=date.weekday())
        bucket = grouped.setdefault(start, {'week_start': start.isoformat(), 'contributions': 0, 'days': 0})
        bucket['contributions'] += count
        bucket['days'] += 1
    rows = [grouped[d] for d in sorted(grouped)]
    if sum(w['contributions'] for w in rows) != sum(d[2] for d in days):
        raise ValueError('Weekly totals do not match daily data')
    return rows


def nice_axis(maximum):
    target = max(1, maximum / 4)
    magnitude = 10 ** math.floor(math.log10(target))
    step = next(s * magnitude for s in [1, 2, 5, 10] if s * magnitude >= target)
    step = max(1, int(step))
    return step, max(step, math.ceil(maximum / step) * step)


def render(user, repos, days, fetched_at=None):
    weeks = weekly_totals(days)
    total = sum(d[2] for d in days)
    stars = sum(r['stargazers_count'] for r in repos if not r['fork'])
    now = fetched_at or dt.datetime.now(dt.timezone.utc)
    stamp = now.strftime('%d %b %Y')
    svg = ['<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="460" viewBox="0 0 1200 460" role="img" aria-labelledby="t d">',
           '<title id="t">Dhruv’s GitHub statistics and contribution trend</title>',
           f'<desc id="d">{total} contributions over 365 days, {user["public_repos"]} public repositories, {stars} stars on owned non-fork public repositories, {user["followers"]} followers. Line chart: contribution totals per Monday-Sunday week. Edge weeks are partial. Refreshed {stamp} UTC.</desc>',
           '<defs><linearGradient id="area" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#edb271" stop-opacity="0.24"/><stop offset="1" stop-color="#edb271" stop-opacity="0.015"/></linearGradient></defs>',
           '<rect x="1" y="1" width="1198" height="458" rx="13" fill="#160f0e" stroke="#73523e" stroke-width="2"/>']

    def text(x, y, value, size=16, color='#f5dfbd', weight='normal', family='monospace', anchor='start'):
        svg.append(f'<text x="{x}" y="{y}" text-anchor="{anchor}" font-family="{family}" font-size="{size}" font-weight="{weight}" fill="{color}">{escape(str(value))}</text>')

    metrics = [(f'{total:,}', 'CONTRIBUTIONS / 365 DAYS', '#edb271'),
               (user['public_repos'], 'PUBLIC REPOSITORIES', '#bc8b60'),
               (stars, 'STARS / NON-FORK REPOS', '#c35849'),
               (user['followers'], 'FOLLOWERS', '#edb271')]
    for i, (value, label, color) in enumerate(metrics):
        x = 30 + i * 293
        text(x, 62, value, 43, color, 'bold', 'Arial,Helvetica,sans-serif')
        text(x, 88, label, 12, '#cdb29b')
        if i:
            svg.append(f'<path d="M{x-20} 27V94" stroke="#4d352b"/>')
    svg.append('<path d="M30 111H1170" stroke="#4d352b"/>')
    text(30, 143, 'A YEAR OF BUILDING', 16, '#edb271', 'bold')
    text(1168, 143, f'REFRESHED {stamp.upper()} / UTC', 12, '#cdb29b', anchor='end')
    text(74, 179, 'Contributions / week', 13, '#cdb29b', family='Arial,Helvetica,sans-serif')
    left, right, top, bottom = 74, 1150, 202, 356
    step, ymax = nice_axis(max(w['contributions'] for w in weeks))
    px = lambda i: left + i * (right-left) / (len(weeks)-1)
    py = lambda value: bottom - value / ymax * (bottom-top)
    for tick in range(0, ymax+1, step):
        y = py(tick)
        svg.append(f'<path d="M{left} {y:.2f}H{right}" stroke="#3b2921" stroke-width="1"/>')
        text(left-13, round(y+4, 2), tick, 12, '#cdb29b', anchor='end')
    points = [(px(i), py(w['contributions'])) for i, w in enumerate(weeks)]
    line = ' '.join(f'{x:.2f},{y:.2f}' for x,y in points)
    svg.append(f'<polygon points="{left},{bottom} {line} {right},{bottom}" fill="url(#area)"/>')
    # Use straight segments: interpolation must not invent peaks or negative values.
    solid = points[:-1] if weeks[-1]['days'] < 7 else points
    solid_line = ' '.join(f'{x:.2f},{y:.2f}' for x,y in solid)
    svg.append(f'<polyline points="{solid_line}" fill="none" stroke="#edb271" stroke-width="3" stroke-linejoin="round" stroke-linecap="round"/>')
    if weeks[-1]['days'] < 7:
        a, b = points[-2:]
        svg.append(f'<path d="M{a[0]:.2f} {a[1]:.2f}L{b[0]:.2f} {b[1]:.2f}" stroke="#edb271" stroke-width="3" stroke-dasharray="5 5" fill="none"/>')
    previous_month = None
    ticks = []
    for i, w in enumerate(weeks):
        week = dt.date.fromisoformat(w['week_start'])
        if (week.year, week.month) != previous_month:
            label = week.strftime('%b %y') if i == 0 or week.month == 1 else week.strftime('%b')
            ticks.append((px(i), label))
            previous_month = (week.year, week.month)
    for x, label in ticks:
        svg.append(f'<path d="M{x:.2f} {bottom}V{bottom+5}" stroke="#73523e"/>')
        text(round(x,2), bottom+25, label, 12, '#cdb29b', anchor='middle')
    for i, (w, (x,y)) in enumerate(zip(weeks,points)):
        week = dt.date.fromisoformat(w['week_start'])
        visible_start, visible_end = max(week, days[0][0]), min(week+dt.timedelta(days=6), days[-1][0])
        partial = w['days'] < 7
        fill = '#160f0e' if partial else '#edb271'
        svg.append(f'<circle cx="{x:.2f}" cy="{y:.2f}" r="{4 if partial else 2.5}" fill="{fill}" stroke="#edb271" stroke-width="1.5"><title>{visible_start} to {visible_end}: {w["contributions"]} contributions{", partial week" if partial else ""}</title></circle>')
    text(612, 406, 'Week · Monday–Sunday', 12, '#cdb29b', family='Arial,Helvetica,sans-serif', anchor='middle')
    text(30, 438, f'{days[0][0].strftime("%d %b %Y")} — {days[-1][0].strftime("%d %b %Y")} / PUBLIC GITHUB DATA', 12, '#cdb29b')
    text(1170, 438, 'EDGE WEEKS PARTIAL · DAILY REFRESH', 11, '#cdb29b', anchor='end')
    svg.append('</svg>')
    return '\n'.join(svg)+'\n'


def main():
    user = json.loads(fetch(f'https://api.github.com/users/{USER}'))
    repos, page = [], 1
    while True:
        batch = json.loads(fetch(f'https://api.github.com/users/{USER}/repos?per_page=100&type=owner&page={page}'))
        repos.extend(batch)
        if len(batch)<100:
            break
        page+=1
    parser=CalendarParser()
    parser.feed(fetch(f'https://github.com/users/{USER}/contributions'))
    days=parser.days()
    now=dt.datetime.now(dt.timezone.utc)
    result=render(user,repos,days,now)
    data={'username':USER, 'fetched_at_utc':now.isoformat(),
          'source':f'https://github.com/users/{USER}/contributions',
          'summary':{'contributions_365_days':sum(d[2] for d in days), 'public_repositories':user['public_repos'],
                     'stars_non_fork_public_repos':sum(r['stargazers_count'] for r in repos if not r['fork']), 'followers':user['followers']},
          'daily':[{'date':d.isoformat(),'contributions':n} for d,_level,n in days], 'weekly':weekly_totals(days)}
    outputs={'activity.svg':result, 'activity-data.json':json.dumps(data,indent=2)+'\n'}
    for name, content in outputs.items():
        destination=ROOT/'assets'/name
        temporary=destination.with_suffix('.tmp')
        temporary.write_text(content,encoding='utf-8')
        temporary.replace(destination)
    print(f'Updated {len(days)} daily records and {len(data["weekly"])} weekly points; {data["summary"]["contributions_365_days"]} contributions.')


if __name__=='__main__':
    main()
