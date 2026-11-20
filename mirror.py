#!/usr/bin/env python3
"""
This script renders a static HTML mirror from a Discourse archive created by
`archive.py`.

It reads the per-post JSON files under `<target-dir>/posts`, groups them into
topics, and writes one minimal HTML page per topic (all posts in order, using
the server-rendered `cooked` HTML) plus a flat `index.html` listing topics with
the most recently active first.
"""
import argparse
import re
import os
import json
import html
import shutil
import functools
import datetime
import dataclasses
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

import logging

loglevel = 'DEBUG' if os.environ.get('DEBUG') else 'INFO'
try:
    # If `rich` is installed, use pretty logging.
    from rich.logging import RichHandler
    logging.basicConfig(level=loglevel, datefmt="[%X]", handlers=[RichHandler()])
except ImportError:
    logging.basicConfig(level=loglevel)

log = logging.getLogger('mirror')


parser = argparse.ArgumentParser(
    'discourse-mirror',
    description='Render a static HTML mirror from a Discourse archive')
parser.add_argument(
    '-u', '--url', help='URL of the source Discourse server (used to make '
    'relative links in the archived HTML absolute)',
    default=os.environ.get('DISCOURSE_URL', 'https://delvingbitcoin.org'))
parser.add_argument(
    '--debug', action='store_true', default=os.environ.get('DEBUG'))
parser.add_argument(
    '-t', '--target-dir', help='Directory of the archive to read',
    default=Path(os.environ.get('TARGET_DIR', './archive')))
parser.add_argument(
    '-o', '--output-dir', help='Directory to write the rendered site into',
    default=Path(os.environ.get('OUTPUT_DIR', './site')))
parser.add_argument(
    '-s', '--site-url', help='URL where the mirror itself will be deployed '
    '(used for og:url tags). Optional.',
    default=os.environ.get('SITE_URL'))


@functools.cache
def args():
    return parser.parse_args()


# Match `href="/path"` or `src="/path"` where the path starts with a single
# slash. The negative lookahead `(?!/)` leaves protocol-relative `//cdn/...`
# URLs untouched, and absolute (`http://...`) and anchor (`#...`) URLs don't
# match in the first place.
_REL_LINK_RE = re.compile(r'(?P<attr>href|src)="/(?!/)')

# Matches the URL of a file uploaded to Discourse, in all its variants
# (original, optimized/resized, extension-less download link). All variants
# embed the SHA-1 of the original file, which the archived copy under
# `<target-dir>/uploads/<sha1>.<ext>` is keyed on.
#
# Keep in sync with the copy in archive.py.
_UPLOAD_URL_RE = re.compile(
    r'(?:https?:)?(?://[^/"\s]+)?/uploads/(?P<db>[^/"\s]+)/'
    r'(?:(?P<kind>original|optimized)/\dX/(?:[0-9a-f]/)*)?'
    r'(?P<sha1>[0-9a-f]{40})'
    r'(?:_\d+_\d+x\d+)?'
    r'(?:\.(?P<ext>[A-Za-z0-9]+))?')

# The same, but only when the URL is the entire value of an HTML attribute
# (`src`, `href`, `data-download-href`, ...), so URLs in visible text or code
# samples are left alone.
_UPLOAD_ATTR_RE = re.compile(r'(?<=")' + _UPLOAD_URL_RE.pattern + r'(?=")')

# A `srcset` attribute (including its leading whitespace) that references
# uploads. Discourse emits these for lightboxed images, listing the resized
# variants plus the original at 2x.
_UPLOAD_SRCSET_RE = re.compile(r'\s+srcset="[^"]*/uploads/[^"]*"')


# The mirror's stylesheet, written to `<output-dir>/style.css` and linked
# from every page.
STYLESHEET = '''/* The mirror's stylesheet.
 *
 * It follows Discourse's own default theme: the same color roles
 * (`--primary` for text, `--secondary` for the background, `--tertiary` for
 * links and accents), a similar topic list and post layout, and styling for
 * the markup that Discourse's server-rendered post HTML brings with it
 * (quotes, oneboxes, mentions, lightboxed images, footnotes, tables).
 */

:root {
  color-scheme: light;
  --primary: #222222;
  --primary-medium: #646464;
  --primary-low-mid: #999999;
  --primary-low: #e9e9e9;
  --primary-very-low: #f4f4f4;
  --secondary: #ffffff;
  --tertiary: #0088cc;
  --tertiary-low: #e5f3f9;
  --highlight-low: #fdf8c3;
  --warning-bg: #fff8e6;
  --warning-border: #f0c36d;
  --warning-text: #7a5b00;
  --shadow: rgba(0, 0, 0, 0.07);
  --font: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto,
    "Helvetica Neue", Arial, sans-serif;
  --mono: ui-monospace, SFMono-Regular, "SF Mono", Menlo, Consolas,
    "Liberation Mono", monospace;
}

/* Discourse's default dark scheme, used when the viewer's system asks for a
 * dark theme and they haven't overridden it here... */
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    color-scheme: dark;
    --primary: #dddddd;
    --primary-medium: #9b9b9b;
    --primary-low-mid: #767676;
    --primary-low: #333333;
    --primary-very-low: #1e1e1e;
    --secondary: #111111;
    --tertiary: #3c9fd4;
    --tertiary-low: #17313d;
    --highlight-low: #4a3c16;
    --warning-bg: #302812;
    --warning-border: #7a5b00;
    --warning-text: #e3c66d;
    --shadow: rgba(0, 0, 0, 0.5);
  }
}

/* ...and whenever they pick dark with the header's toggle. */
:root[data-theme="dark"] {
  color-scheme: dark;
  --primary: #dddddd;
  --primary-medium: #9b9b9b;
  --primary-low-mid: #767676;
  --primary-low: #333333;
  --primary-very-low: #1e1e1e;
  --secondary: #111111;
  --tertiary: #3c9fd4;
  --tertiary-low: #17313d;
  --highlight-low: #4a3c16;
  --warning-bg: #302812;
  --warning-border: #7a5b00;
  --warning-text: #e3c66d;
  --shadow: rgba(0, 0, 0, 0.5);
}

* {
  box-sizing: border-box;
}

html {
  -webkit-text-size-adjust: 100%;
}

body {
  margin: 0;
  background: var(--secondary);
  color: var(--primary);
  font-family: var(--font);
  font-size: 15px;
  line-height: 1.5;
}

a {
  color: var(--tertiary);
  text-decoration: none;
}

a:hover {
  text-decoration: underline;
}

/* --- Page chrome ---------------------------------------------------- */

.wrap {
  max-width: 62rem;
  margin: 0 auto;
  padding: 0 1rem;
}

.site-header {
  position: sticky;
  top: 0;
  z-index: 10;
  background: var(--secondary);
  border-bottom: 1px solid var(--primary-low);
  box-shadow: 0 2px 4px -2px var(--shadow);
}

.site-header .wrap {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  min-height: 3.25rem;
  flex-wrap: wrap;
}

.site-title {
  font-weight: 700;
  font-size: 1.05rem;
  color: var(--primary);
  margin-right: auto;
}

.site-title:hover {
  text-decoration: none;
  color: var(--tertiary);
}

.site-nav {
  display: flex;
  align-items: center;
  gap: 0.15rem;
}

.site-nav a {
  padding: 0.35rem 0.6rem;
  border-radius: 0.25rem;
  color: var(--primary-medium);
}

.site-nav a:hover {
  background: var(--primary-very-low);
  color: var(--primary);
  text-decoration: none;
}

.site-nav a[aria-current="page"] {
  background: var(--primary-very-low);
  color: var(--primary);
  font-weight: 600;
}

/* The header's light/dark toggle. It shows the theme it would switch *to*,
 * which is also why the icons are swapped in CSS rather than in script: the
 * right one shows before any JavaScript runs. */
.theme-toggle {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 2rem;
  height: 2rem;
  padding: 0;
  border: 0;
  border-radius: 0.25rem;
  background: none;
  color: var(--primary-medium);
  cursor: pointer;
}

.theme-toggle:hover {
  background: var(--primary-very-low);
  color: var(--primary);
}

.theme-toggle svg {
  width: 1.15rem;
  height: 1.15rem;
  fill: currentColor;
}

.theme-toggle .sun {
  display: none;
}

@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) .theme-toggle .sun {
    display: block;
  }

  :root:not([data-theme="light"]) .theme-toggle .moon {
    display: none;
  }
}

:root[data-theme="dark"] .theme-toggle .sun {
  display: block;
}

:root[data-theme="dark"] .theme-toggle .moon {
  display: none;
}

:root[data-theme="light"] .theme-toggle .sun {
  display: none;
}

:root[data-theme="light"] .theme-toggle .moon {
  display: block;
}

main {
  padding: 1.5rem 0 2rem;
}

.page-title {
  font-size: 1.6rem;
  line-height: 1.25;
  margin: 0 0 0.5rem;
}

.page-subtitle {
  color: var(--primary-medium);
  margin: 0 0 1.5rem;
  font-size: 0.95em;
}

.breadcrumb {
  margin: 0 0 1rem;
  font-size: 0.9em;
  color: var(--primary-medium);
}

footer.build {
  margin-top: 3rem;
  padding: 1rem 0 2rem;
  border-top: 1px solid var(--primary-low);
  font-size: 0.85em;
  color: var(--primary-medium);
  text-align: center;
}

/* --- Topic list ----------------------------------------------------- */

.topic-list {
  width: 100%;
  border-collapse: collapse;
}

.topic-list th {
  padding: 0.5rem;
  text-align: left;
  font-weight: normal;
  font-size: 0.9em;
  color: var(--primary-medium);
  border-bottom: 2px solid var(--primary-low);
}

.topic-list td {
  padding: 0.7rem 0.5rem;
  border-bottom: 1px solid var(--primary-low);
  vertical-align: middle;
}

.topic-list tbody tr:hover td {
  background: var(--primary-very-low);
}

.topic-list .title {
  font-size: 1.05em;
  font-weight: 500;
  color: var(--primary);
}

.topic-list .title:hover {
  color: var(--tertiary);
  text-decoration: none;
}

.topic-list .title:visited {
  color: var(--primary-medium);
}

.topic-badges {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.35rem;
  margin-top: 0.3rem;
}

.topic-list th.num,
.topic-list td.num {
  width: 4.5rem;
  text-align: right;
  white-space: nowrap;
  color: var(--primary-medium);
  font-size: 0.9em;
}

.topic-list .posters {
  width: 9.5rem;
  white-space: nowrap;
}

img.poster {
  width: 25px;
  height: 25px;
  border-radius: 50%;
  margin-right: 0.25rem;
  vertical-align: middle;
}

/* The original poster and whoever posted last are the two faces worth
 * telling apart, as Discourse does. */
img.poster.op {
  box-shadow: 0 0 0 2px var(--tertiary);
}

img.poster.latest {
  box-shadow: 0 0 0 2px var(--primary-low-mid);
}

.badge-category {
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
  padding: 0.1rem 0.4rem;
  border-radius: 0.2rem;
  background: var(--primary-very-low);
  color: var(--primary-medium);
  font-size: 0.85em;
}

.badge-category::before {
  content: "";
  flex: none;
  width: 0.65em;
  height: 0.65em;
  border-radius: 2px;
  background: var(--category-color, var(--primary-low-mid));
}

.discourse-tag {
  padding: 0.1rem 0.4rem;
  border-radius: 0.2rem;
  background: var(--primary-very-low);
  color: var(--primary-medium);
  font-size: 0.8em;
}

/* Narrow screens: the columns stack under the title, labelled by the
 * `data-label` the renderer puts on each of them. */
@media (max-width: 45rem) {
  .topic-list thead {
    display: none;
  }

  .topic-list,
  .topic-list tbody,
  .topic-list tr,
  .topic-list td {
    display: block;
    width: auto;
  }

  .topic-list tr {
    padding: 0.7rem 0;
    border-bottom: 1px solid var(--primary-low);
  }

  .topic-list td {
    padding: 0.15rem 0;
    border: 0;
  }

  .topic-list td.num {
    display: inline-block;
    width: auto;
    margin-right: 1rem;
    text-align: left;
  }

  .topic-list td.num::before {
    content: attr(data-label) " ";
  }

  .topic-list .posters {
    margin-top: 0.3rem;
  }
}

/* --- Topic page ----------------------------------------------------- */

.topic .wrap {
  max-width: 53rem;
}

.topic-header {
  border-bottom: 1px solid var(--primary-low);
  padding-bottom: 0.75rem;
  margin-bottom: 0.5rem;
}

.topic-meta {
  color: var(--primary-medium);
  font-size: 0.9em;
}

.post {
  display: grid;
  grid-template-columns: 45px minmax(0, 1fr);
  gap: 0 0.85rem;
  padding: 1.25rem 0;
  border-top: 1px solid var(--primary-low);
}

.post:first-of-type {
  border-top: 0;
}

.post:target {
  background: var(--highlight-low);
  box-shadow: 0 0 0 0.5rem var(--highlight-low);
  border-radius: 2px;
}

.post-avatar img {
  width: 45px;
  height: 45px;
  border-radius: 50%;
  display: block;
}

.post-main {
  min-width: 0;
}

.post-header {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 0.5rem;
  margin-bottom: 0.4rem;
}

.post-author {
  font-weight: 700;
  color: var(--primary);
}

.post-info {
  margin-left: auto;
  display: flex;
  align-items: baseline;
  gap: 0.6rem;
  color: var(--primary-low-mid);
  font-size: 0.85em;
}

.post-info a {
  color: var(--primary-low-mid);
}

.post-info a:hover {
  color: var(--primary-medium);
}

.reply-to {
  display: inline-block;
  font-size: 0.85em;
  color: var(--primary-medium);
  margin-bottom: 0.4rem;
}

.missing-posts {
  border: 1px solid var(--warning-border);
  background: var(--warning-bg);
  color: var(--warning-text);
  border-radius: 0.25rem;
  padding: 0.5rem 1rem;
  margin: 1rem 0;
  font-size: 0.9em;
}

/* --- Post content (Discourse's "cooked" HTML) ----------------------- */

.cooked > *:first-child {
  margin-top: 0;
}

.cooked > *:last-child {
  margin-bottom: 0;
}

.cooked p {
  margin: 0 0 1em;
}

.cooked h1,
.cooked h2,
.cooked h3,
.cooked h4 {
  line-height: 1.25;
  margin: 1.5em 0 0.5em;
}

.cooked h1 {
  font-size: 1.4em;
}

.cooked h2 {
  font-size: 1.25em;
}

.cooked h3 {
  font-size: 1.1em;
}

.cooked img {
  max-width: 100%;
  height: auto;
}

.cooked hr {
  border: 0;
  border-top: 1px solid var(--primary-low);
  margin: 1.5em 0;
}

.cooked code {
  font-family: var(--mono);
  font-size: 0.875em;
  background: var(--primary-very-low);
  padding: 0.1em 0.3em;
  border-radius: 0.2rem;
}

.cooked pre {
  background: var(--primary-very-low);
  border-radius: 0.3rem;
  padding: 0.75rem;
  overflow-x: auto;
  margin: 1em 0;
}

.cooked pre code {
  background: none;
  padding: 0;
  font-size: 0.85em;
  line-height: 1.45;
}

.cooked blockquote {
  margin: 1em 0;
  padding: 0.6em 1em;
  border-left: 5px solid var(--primary-low);
  background: var(--primary-very-low);
}

.cooked blockquote > *:first-child {
  margin-top: 0;
}

.cooked blockquote > *:last-child {
  margin-bottom: 0;
}

/* Quoting another post: a header naming the quoted author, then the quote. */
aside.quote {
  margin: 1em 0;
}

aside.quote .title {
  padding: 0.5em 0.8em;
  border: 1px solid var(--primary-low);
  border-bottom: 0;
  border-left: 5px solid var(--primary-low);
  background: var(--primary-very-low);
  color: var(--primary-medium);
  font-size: 0.9em;
}

aside.quote .title img.avatar {
  width: 20px;
  height: 20px;
  border-radius: 50%;
  vertical-align: -0.3em;
  margin-right: 0.35em;
}

aside.quote .quote-controls {
  display: none;
}

aside.quote blockquote {
  margin: 0;
  border: 1px solid var(--primary-low);
  border-left: 5px solid var(--primary-low);
  background: var(--secondary);
}

.cooked table {
  border-collapse: collapse;
  margin: 1em 0;
}

.cooked th,
.cooked td {
  border: 1px solid var(--primary-low);
  padding: 0.4em 0.7em;
  text-align: left;
}

.cooked thead th {
  background: var(--primary-very-low);
}

.md-table {
  overflow-x: auto;
  margin: 1em 0;
}

.md-table table {
  margin: 0;
}

a.mention,
a.hashtag-cooked {
  background: var(--primary-very-low);
  color: var(--primary-medium);
  padding: 0.1em 0.35em;
  border-radius: 0.6em;
  font-size: 0.93em;
}

a.mention:hover,
a.hashtag-cooked:hover {
  background: var(--tertiary-low);
  color: var(--primary);
  text-decoration: none;
}

.hashtag-icon-placeholder {
  display: none;
}

img.emoji {
  width: 1.2em;
  height: 1.2em;
  vertical-align: -0.2em;
}

.only-emoji img.emoji {
  width: 2em;
  height: 2em;
}

/* TeX that Discourse's math plugin renders client-side; without it, show the
 * source as code rather than as broken prose. */
span.math {
  font-family: var(--mono);
  font-size: 0.9em;
  background: var(--primary-very-low);
  padding: 0.1em 0.3em;
  border-radius: 0.2rem;
}

div.math {
  font-family: var(--mono);
  font-size: 0.9em;
  background: var(--primary-very-low);
  border-radius: 0.3rem;
  padding: 0.6em 0.75em;
  margin: 1em 0;
  overflow-x: auto;
  white-space: pre-wrap;
}

.discourse-local-date {
  background: var(--primary-very-low);
  padding: 0.1em 0.3em;
  border-radius: 0.2rem;
}

.footnotes {
  margin-top: 1.5em;
  padding-top: 0.5em;
  border-top: 1px solid var(--primary-low);
  font-size: 0.9em;
  color: var(--primary-medium);
}

/* Discourse's lightbox chrome: the caption bar carries unsized <svg> icons
 * that, without Discourse's CSS, fall back to the 300x150 default and leave a
 * big gap under each image. It is only useful for the (absent) JS lightbox. */
.lightbox-wrapper .meta {
  display: none;
}

svg.d-icon {
  width: 1em;
  height: 1em;
  fill: currentColor;
}

/* --- Oneboxes (rich link previews) ---------------------------------- */

aside.onebox {
  border: 1px solid var(--primary-low);
  border-left-width: 5px;
  border-radius: 0.25rem;
  padding: 0.75rem 1rem;
  margin: 1em 0;
  overflow: hidden;
}

aside.onebox .source {
  font-size: 0.85em;
  color: var(--primary-medium);
  margin-bottom: 0.5rem;
}

aside.onebox .source .site-icon {
  width: 1em;
  height: 1em;
  vertical-align: text-bottom;
  margin-right: 0.35em;
}

aside.onebox .onebox-body {
  overflow: hidden;
}

aside.onebox .onebox-body h3,
aside.onebox .onebox-body h4 {
  margin: 0.2em 0;
  font-size: 1.05em;
}

aside.onebox .onebox-body p {
  margin: 0.4em 0;
}

aside.onebox .aspect-image,
aside.onebox .onebox-body img.thumbnail {
  float: right;
  max-width: 25%;
  height: auto;
  margin: 0 0 0.5rem 1rem;
}

/* GitHub-blob oneboxes wrap an <ol class="lines"> in a <pre>, whose literal
 * newlines and indentation render as blank lines without Discourse's CSS.
 * Reset the pre's whitespace and render the list as a line-numbered block. */
pre.onebox {
  white-space: normal;
  background: none;
  padding: 0;
  margin: 0.5rem 0;
}

pre.onebox ol.lines {
  list-style: none;
  margin: 0;
  padding: 0.5rem;
  font-family: var(--mono);
  font-size: 0.85em;
  background: var(--primary-very-low);
  border-radius: 0.25rem;
  overflow-x: auto;
}

pre.onebox ol.lines li {
  counter-increment: li-counter;
  white-space: pre;
}

pre.onebox ol.lines li::before {
  content: counter(li-counter);
  display: inline-block;
  width: 3em;
  margin-right: 1em;
  color: var(--primary-low-mid);
  text-align: right;
}

@media (max-width: 40rem) {
  .post {
    grid-template-columns: 30px minmax(0, 1fr);
    gap: 0 0.6rem;
  }

  .post-avatar img {
    width: 30px;
    height: 30px;
  }

  .post-info {
    margin-left: 0;
  }
}
'''


def render_build_footer() -> str:
    built = format_datetime(datetime.datetime.now(datetime.timezone.utc))
    return ('<footer class="build"><div class="wrap">'
            f'Mirror of <a href="{html.escape(args().url.rstrip("/"))}">'
            f'{html.escape(source_host())}</a>, built {html.escape(built)}'
            '</div></footer>')


def source_host() -> str:
    return urlparse(args().url).netloc or args().url


def site_url_for(filename: str) -> str | None:
    """Absolute URL of `filename` on the deployed mirror, if --site-url is set."""
    base = args().site_url
    if not base:
        return None
    return f"{base.rstrip('/')}/{filename}"


def rewrite_links(cooked: str, base_url: str) -> str:
    """Rewrite root-relative links/images to absolute URLs on the source site."""
    base = base_url.rstrip('/')
    return _REL_LINK_RE.sub(rf'\g<attr>="{base}/', cooked)


def load_uploads(uploads_dir: Path) -> dict[str, str]:
    """Map sha1 -> filename for the uploads archived under `uploads_dir`."""
    if not uploads_dir.is_dir():
        return {}
    return {p.stem: p.name for p in uploads_dir.iterdir() if p.is_file()}


def rewrite_uploads(cooked: str, uploads: dict[str, str], missing: set[str]) -> str:
    """Point references to uploads at the archived copies under `uploads/`.

    Only the original of each upload is archived, so every variant (the
    resized `optimized` thumbnails, the lightbox's full-size link and download
    link) is rewritten to the same local file, and `srcset` attributes are
    dropped: the `<img>` keeps its width/height, so layout is unchanged and
    the browser scales the original down.

    Uploads not found in the archive are left pointing at the source site and
    their sha1 is added to `missing`.
    """
    def sub_srcset(m: re.Match) -> str:
        sha1s = {u.group('sha1') for u in _UPLOAD_URL_RE.finditer(m.group(0))}
        return '' if any(s in uploads for s in sha1s) else m.group(0)

    def sub_url(m: re.Match) -> str:
        filename = uploads.get(m.group('sha1'))
        if filename is None:
            missing.add(m.group('sha1'))
            return m.group(0)
        return f'uploads/{filename}'

    cooked = _UPLOAD_SRCSET_RE.sub(sub_srcset, cooked)
    return _UPLOAD_ATTR_RE.sub(sub_url, cooked)


def copy_uploads(uploads_dir: Path, output_dir: Path) -> int:
    """Copy archived uploads into `<output-dir>/uploads`; returns the number copied.

    Files already present with the same size and a mtime at least as new are
    skipped, so re-running the mirror is cheap.
    """
    dest_dir = output_dir / 'uploads'
    dest_dir.mkdir(parents=True, exist_ok=True)
    copied = 0
    for src in uploads_dir.iterdir():
        if not src.is_file():
            continue
        dest = dest_dir / src.name
        if dest.exists():
            s, d = src.stat(), dest.stat()
            if s.st_size == d.st_size and d.st_mtime >= s.st_mtime:
                continue
        shutil.copy2(src, dest)
        copied += 1
    return copied


def format_datetime(dt: datetime.datetime) -> str:
    """Human-friendly rendering of a post timestamp, e.g. "29 Jan 2025, 11:17 UTC"."""
    return dt.strftime('%d %b %Y, %H:%M UTC')


def format_relative(dt: datetime.datetime,
                    now: datetime.datetime | None = None) -> str:
    """Short "how long ago" label for a topic list, the way Discourse writes it.

    Recent activity is counted in minutes, hours or days; anything older is
    given as a date, with the year once it isn't this one ("12 Jan", "Mar '24").
    """
    now = now or datetime.datetime.now(datetime.timezone.utc)
    seconds = (now - dt).total_seconds()
    if seconds < 3600:
        return f'{max(int(seconds // 60), 1)}m'
    if seconds < 86400:
        return f'{int(seconds // 3600)}h'
    if seconds < 86400 * 30:
        return f'{int(seconds // 86400)}d'
    if dt.year == now.year:
        return dt.strftime('%-d %b')
    return dt.strftime("%b '%y")


def format_count(n: int) -> str:
    """Compact count for the topic list, e.g. 1489 -> "1.5k"."""
    if n < 1000:
        return str(n)
    if n < 1000000:
        return f'{n / 1000:.1f}k'.replace('.0k', 'k')
    return f'{n / 1000000:.1f}M'.replace('.0M', 'M')


_AVATAR_SIZE = 48


def avatar_url(avatar_template: str, base_url: str) -> str:
    """Absolute URL for a post author's avatar, or '' if there is none."""
    if not avatar_template:
        return ''
    url = avatar_template.replace('{size}', str(_AVATAR_SIZE))
    if url.startswith('//'):
        return f'https:{url}'
    if url.startswith('/'):
        return f"{base_url.rstrip('/')}{url}"
    return url


_TAG_RE = re.compile(r'<[^>]+>')


def extract_description(post: 'MirrorPost', max_len: int = 200) -> str:
    """Plain-text excerpt for og:description, taken from the first post."""
    text = post.raw.get('excerpt') or post.raw.get('raw') or ''
    text = _TAG_RE.sub('', text)
    text = html.unescape(text)
    text = ' '.join(text.split())
    if len(text) > max_len:
        text = text[:max_len].rsplit(' ', 1)[0] + '…'
    return text


@dataclass(frozen=True)
class MirrorPost:
    raw: dict

    @property
    def post_number(self) -> int:
        return self.raw['post_number']

    @property
    def author(self) -> str:
        return self.raw.get('name') or self.raw['username']

    @property
    def username(self) -> str:
        return self.raw['username']

    @property
    def cooked(self) -> str:
        return self.raw.get('cooked') or ''

    @property
    def post_url(self) -> str:
        return self.raw.get('post_url') or ''

    @property
    def avatar_template(self) -> str:
        return self.raw.get('avatar_template') or ''

    @property
    def reply_to_post_number(self) -> int | None:
        return self.raw.get('reply_to_post_number')

    def get_created_at(self) -> datetime.datetime:
        return datetime.datetime.fromisoformat(self.raw['created_at'])

    @property
    def created_at_display(self) -> str:
        return format_datetime(self.get_created_at())

    def get_updated_at(self) -> datetime.datetime:
        return datetime.datetime.fromisoformat(
            self.raw.get('updated_at') or self.raw['created_at'])


_SLUG_RE = re.compile(r'[^a-z0-9]+')


def slugify(name: str) -> str:
    """A filename-safe form of a tag name, e.g. "lang:rust" -> "lang-rust"."""
    return _SLUG_RE.sub('-', name.lower()).strip('-') or 'tag'


@dataclass(frozen=True)
class MirrorTag:
    name: str
    slug: str

    @classmethod
    def parse(cls, tag: dict | str) -> 'MirrorTag':
        """Read one entry of a topic's `tags`.

        Discourse gives them either as plain names or, on newer versions, as
        `{id, name, slug}` objects -- both show up in the same archive.
        """
        if isinstance(tag, dict):
            name = tag.get('name') or tag.get('slug') or ''
            return cls(name, tag.get('slug') or slugify(name))
        return cls(tag, slugify(tag))


@dataclass(frozen=True)
class MirrorCategory:
    """A category of the source site, from `<target-dir>/categories.json`."""
    id: int
    name: str
    slug: str
    color: str
    description: str
    parent_id: int | None
    parent: 'MirrorCategory | None' = None

    @property
    def full_name(self) -> str:
        """"Parent / Child" for a subcategory, just the name otherwise."""
        if self.parent:
            return f'{self.parent.name} / {self.name}'
        return self.name


def load_categories(path: Path) -> dict[int, MirrorCategory]:
    """Read the archived category list, keyed by id.

    Returns an empty mapping if the archive predates `--backfill-topics`; the
    mirror then simply doesn't show categories.
    """
    if not path.is_file():
        return {}
    raw = json.loads(path.read_text()).get('categories') or []
    categories = {
        c['id']: MirrorCategory(
            id=c['id'],
            name=c.get('name') or '',
            slug=c.get('slug') or str(c['id']),
            color=c.get('color') or '',
            description=c.get('description_text') or '',
            parent_id=c.get('parent_category_id'),
        )
        for c in raw
    }
    # Link subcategories to their parent now that they're all loaded.
    return {
        i: dataclasses.replace(c, parent=categories.get(c.parent_id))
        for i, c in categories.items()
    }


def load_topic_metadata(topics_dir: Path) -> dict[int, dict]:
    """Read the archived topic metadata (see archive.py), keyed by topic id."""
    if not topics_dir.is_dir():
        return {}
    metadata = {}
    for path in topics_dir.glob('**/*.json'):
        raw = json.loads(path.read_text())
        if 'id' in raw:
            metadata[raw['id']] = raw
    return metadata


def category_colors(categories: dict[int, MirrorCategory]) -> str:
    """A `--category-color` rule per category, appended to the stylesheet.

    Discourse gives every category a color; keeping them out of the HTML means
    the badges stay plain markup and the colors stay in one place.
    """
    rules = [f'.category-{c.id} {{ --category-color: #{c.color}; }}'
             for c in sorted(categories.values(), key=lambda c: c.id)
             if re.fullmatch(r'[0-9A-Fa-f]{3,8}', c.color or '')]
    if not rules:
        return ''
    return '\n/* --- Category colors (from the source site) ---------- */\n\n' \
        + '\n'.join(rules) + '\n'


def write_stylesheet(output_dir: Path,
                     categories: dict[int, MirrorCategory]) -> None:
    (output_dir / 'style.css').write_text(
        STYLESHEET + category_colors(categories))


@dataclass
class MirrorTopic:
    id: int
    slug: str
    title: str
    posts: list[MirrorPost] = field(default_factory=list)
    # The archived topic metadata, empty for an archive that has none. It is
    # the only source for what isn't on the posts: category, tags, views.
    meta: dict = field(default_factory=dict)
    category: MirrorCategory | None = None

    @property
    def last_activity(self) -> datetime.datetime:
        return max(p.get_updated_at() for p in self.posts)

    @property
    def first_created(self) -> datetime.datetime:
        return min(p.get_created_at() for p in self.posts)

    @property
    def author(self) -> str:
        """The original poster (posts are sorted by post_number)."""
        return self.posts[0].author

    @property
    def filename(self) -> str:
        date = str(self.first_created.date())
        return f"{date}-{self.slug}-id{self.id}.html"

    @property
    def tags(self) -> list[MirrorTag]:
        return [MirrorTag.parse(t) for t in (self.meta.get('tags') or [])]

    @property
    def views(self) -> int | None:
        return self.meta.get('views')

    @property
    def reply_count(self) -> int:
        """Replies the way Discourse counts them: every post but the first.

        Taken from the topic's own post count where known, so a topic whose
        posts aren't all archived still reports what the source site says.
        """
        return max((self.meta.get('posts_count') or len(self.posts)) - 1, 0)


def render_missing_posts(previous_post_number: int, next_post_number: int) -> str:
    """Warning box for post numbers missing between two consecutive posts.

    A gap means the post was either never fetched or is gone from the source
    (deleted/moderated) -- we can't tell which from the archive alone.
    """
    missing = next_post_number - previous_post_number - 1
    if missing <= 0:
        return ''
    if missing == 1:
        label = f'post #{previous_post_number + 1}'
    else:
        label = f'posts #{previous_post_number + 1}&ndash;#{next_post_number - 1}'
    return (
        '<!-- MIRROR-MISSING-POST -->\n'
        f'<p class="missing-posts">&#9888; {label} missing '
        '(not fetched, or removed/moderated on the source site)</p>')


def archive_title() -> str:
    return f'Archive of {source_host()}'


# Sun and moon glyphs for the theme toggle.
_SUN_ICON = (
    '<svg class="sun" viewBox="0 0 24 24" aria-hidden="true">'
    '<circle cx="12" cy="12" r="4.5"/>'
    '<path fill="none" stroke="currentColor" stroke-width="2" '
    'stroke-linecap="round" d="M12 1.5v3M12 19.5v3M1.5 12h3M19.5 12h3'
    'M4.5 4.5l2.1 2.1M17.4 17.4l2.1 2.1M19.5 4.5l-2.1 2.1M6.6 17.4l-2.1 2.1"/>'
    '</svg>')
_MOON_ICON = (
    '<svg class="moon" viewBox="0 0 24 24" aria-hidden="true">'
    '<path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z"/>'
    '</svg>')

# Applies the viewer's saved theme before the page is painted, so switching
# to dark doesn't flash a white page on every navigation. Without JavaScript
# (or before this runs) the page follows `prefers-color-scheme`.
_THEME_SCRIPT = (
    '<script>try{var t=localStorage.getItem("theme");'
    'if(t)document.documentElement.dataset.theme=t}catch(e){}</script>')

# Flips between light and dark, starting from whatever the page is showing
# now, and remembers the choice for the rest of the mirror.
_TOGGLE_SCRIPT = (
    '<script>document.querySelector(".theme-toggle").addEventListener("click",'
    'function(){var r=document.documentElement,'
    'now=r.dataset.theme||(window.matchMedia("(prefers-color-scheme: dark)")'
    '.matches?"dark":"light"),next=now==="dark"?"light":"dark";'
    'r.dataset.theme=next;'
    'try{localStorage.setItem("theme",next)}catch(e){}});</script>')


def render_header() -> str:
    """The site header shared by every page."""
    base_url = html.escape(args().url.rstrip('/'))
    return (
        '<header class="site-header"><div class="wrap">'
        f'<a class="site-title" href="index.html">{html.escape(archive_title())}</a>'
        '<nav class="site-nav">'
        f'<a href="{base_url}">{html.escape(source_host())} &#8599;</a>'
        '</nav>'
        '<button class="theme-toggle" type="button" title="Switch between '
        'light and dark" aria-label="Switch between light and dark">'
        f'{_SUN_ICON}{_MOON_ICON}</button>'
        '</div></header>')


def render_document(title: str, body: list[str], *, head: list[str] = [],
                    body_class: str = '') -> str:
    """Wrap a page's body in the document shell shared by every page."""
    parts = [
        '<!DOCTYPE html>',
        '<html lang="en">',
        '<head>',
        '<meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        f'<title>{html.escape(title)}</title>',
        '<link rel="stylesheet" href="style.css">',
        _THEME_SCRIPT,
        *head,
        '</head>',
        f'<body class="{body_class}">' if body_class else '<body>',
        render_header(),
        '<main><div class="wrap">',
        *body,
        '</div></main>',
        render_build_footer(),
        _TOGGLE_SCRIPT,
        '</body>',
        '</html>',
        '',
    ]
    return '\n'.join(parts)


def render_post(post: MirrorPost, base_url: str, uploads: dict[str, str],
                missing_uploads: set[str]) -> list[str]:
    """Render one post: an avatar gutter next to the author line and body."""
    avatar = avatar_url(post.avatar_template, base_url)
    gutter = (
        f'<img src="{html.escape(avatar)}" alt="" width="45" height="45" '
        'loading="lazy">' if avatar else '')

    info = [
        f'<a href="{base_url}{html.escape(post.post_url)}">#{post.post_number}</a>',
        f'<time datetime="{html.escape(post.raw["created_at"])}">'
        f'{html.escape(post.created_at_display)}</time>',
        f'<a class="permalink" href="#post-{post.post_number}" '
        'aria-label="permalink">&#128279;</a>',
    ]

    parts = [
        f'<article class="post" id="post-{post.post_number}">',
        f'<div class="post-avatar">{gutter}</div>',
        '<div class="post-main">',
        '<div class="post-header">',
        f'<span class="post-author">{html.escape(post.author)}</span>',
        '<span class="post-info">' + ' '.join(info) + '</span>',
        '</div>',
    ]
    if post.reply_to_post_number:
        parts.append(
            f'<a class="reply-to" href="#post-{post.reply_to_post_number}">'
            f'&#8627; in reply to #{post.reply_to_post_number}</a>')

    cooked = rewrite_uploads(post.cooked, uploads, missing_uploads)
    parts += [
        '<div class="cooked">',
        rewrite_links(cooked, base_url),
        '</div>',
        '</div>',
        '</article>',
    ]
    return parts


def render_topic(topic: MirrorTopic, base_url: str, uploads: dict[str, str],
                 missing_uploads: set[str]) -> str:
    """Render a single topic (with all its posts) to an HTML document.

    `uploads` maps the sha1 of each archived upload to its filename (see
    `load_uploads`); the sha1 of any upload referenced but not archived is
    added to `missing_uploads`.
    """
    title = html.escape(topic.title)
    description = html.escape(extract_description(topic.posts[0]))
    canonical = html.escape(f"{base_url}/t/{topic.slug}/{topic.id}")
    og_url = html.escape(
        site_url_for(topic.filename) or f"{base_url}/t/{topic.slug}/{topic.id}")
    head = [
        f'<link rel="canonical" href="{canonical}">',
        f'<meta property="og:title" content="{title}">',
        f'<meta property="og:description" content="{description}">',
        '<meta property="og:type" content="article">',
        f'<meta property="og:site_name" content="{html.escape(archive_title())}">',
        f'<meta property="og:url" content="{og_url}">',
    ]

    n = len(topic.posts)
    body = [
        '<p class="breadcrumb"><a href="index.html">&larr; all topics</a></p>',
        '<header class="topic-header">',
        f'<h1 class="page-title">{title}</h1>',
        '<p class="topic-meta">'
        f'{n} {"post" if n == 1 else "posts"} &middot; '
        f'started {html.escape(format_datetime(topic.first_created))} &middot; '
        f'<a href="{canonical}">view the original topic &#8599;</a>'
        '</p>',
        '</header>',
    ]

    previous_post_number = None
    for post in topic.posts:
        if previous_post_number is not None:
            gap = render_missing_posts(previous_post_number, post.post_number)
            if gap:
                body.append(gap)
        previous_post_number = post.post_number
        body += render_post(post, base_url, uploads, missing_uploads)

    return render_document(topic.title, body, head=head, body_class='topic')


# Discourse shows at most five faces per topic in its topic list.
_MAX_POSTERS = 5


def topic_posters(topic: MirrorTopic) -> list[tuple[MirrorPost, str]]:
    """The authors to show for a topic, as (one of their posts, role).

    Like Discourse: the original poster first, whoever posted last at the end,
    and the most prolific posters in between, five at most. The roles are what
    the stylesheet uses to mark the first and the latest poster.
    """
    posts_by_author: dict[str, list[MirrorPost]] = {}
    for post in topic.posts:
        posts_by_author.setdefault(post.username, []).append(post)

    first = topic.posts[0].username
    last = topic.posts[-1].username
    middle = sorted(
        (u for u in posts_by_author if u not in (first, last)),
        key=lambda u: (-len(posts_by_author[u]), u))

    usernames = [first] + middle
    if last != first:
        usernames.append(last)
    if len(usernames) > _MAX_POSTERS:
        # Drop from the middle: the first and the latest poster are the two
        # worth keeping.
        usernames = usernames[:_MAX_POSTERS - 1] + usernames[-1:]

    roles = {first: 'op', last: 'latest'}
    return [(posts_by_author[u][-1], roles.get(u, '')) for u in usernames]


def render_posters(topic: MirrorTopic, base_url: str) -> str:
    """The column of author avatars shown for a topic in the topic list."""
    faces = []
    for post, role in topic_posters(topic):
        avatar = avatar_url(post.avatar_template, base_url)
        if not avatar:
            continue
        title = html.escape(post.author)
        if role == 'op':
            title += ' (original poster)'
        elif role == 'latest':
            title += ' (posted last)'
        faces.append(
            f'<img class="poster{" " + role if role else ""}" '
            f'src="{html.escape(avatar)}" '
            f'alt="{html.escape(post.author)}" title="{title}" '
            'width="25" height="25" loading="lazy">')
    return ''.join(faces)


def render_category_badge(category: MirrorCategory | None) -> str:
    """Discourse's category badge: the category's color, then its name."""
    if not category:
        return ''
    return (f'<span class="badge-category category-{category.id}">'
            f'{html.escape(category.full_name)}</span>')


def render_tags(tags: list[MirrorTag]) -> str:
    return ''.join(f'<span class="discourse-tag">{html.escape(t.name)}</span>'
                   for t in tags)


def render_topic_list(topics: list[MirrorTopic], base_url: str) -> list[str]:
    """Discourse's topic list: title, who took part, replies, views, activity."""
    parts = [
        '<table class="topic-list">',
        '<thead><tr>',
        '<th class="topic-list-title">Topic</th>',
        '<th class="posters">Users</th>',
        '<th class="num">Replies</th>',
        '<th class="num">Views</th>',
        '<th class="num">Activity</th>',
        '</tr></thead>',
        '<tbody>',
    ]

    for topic in topics:
        badges = render_category_badge(topic.category) + render_tags(topic.tags)
        activity = topic.last_activity
        views = topic.views
        parts += [
            '<tr>',
            '<td class="topic-list-title">'
            f'<a class="title" href="{html.escape(topic.filename)}">'
            f'{html.escape(topic.title)}</a>'
            + (f'<div class="topic-badges">{badges}</div>' if badges else '')
            + '</td>',
            f'<td class="posters">{render_posters(topic, base_url)}</td>',
            f'<td class="num" data-label="replies">{topic.reply_count}</td>',
            '<td class="num" data-label="views">'
            f'{format_count(views) if views is not None else "&mdash;"}</td>',
            '<td class="num" data-label="activity">'
            f'<time datetime="{html.escape(activity.isoformat())}" '
            f'title="{html.escape(format_datetime(activity))}">'
            f'{html.escape(format_relative(activity))}</time></td>',
            '</tr>',
        ]

    parts += ['</tbody>', '</table>']
    return parts


def render_index(topics: list[MirrorTopic], base_url: str) -> str:
    """Render the index page listing topics, most recently active first."""
    og_url = site_url_for('index.html')
    head = [
        f'<meta property="og:title" content="{html.escape(archive_title())}">',
        '<meta property="og:type" content="website">',
        f'<meta property="og:site_name" content="{html.escape(archive_title())}">',
    ]
    if og_url:
        head.append(f'<meta property="og:url" content="{html.escape(og_url)}">')

    n_posts = sum(len(t.posts) for t in topics)
    body = [
        f'<h1 class="page-title">{html.escape(archive_title())}</h1>',
        f'<p class="page-subtitle">{len(topics)} topics, {n_posts} posts '
        f'archived from <a href="{html.escape(args().url.rstrip("/"))}">'
        f'{html.escape(source_host())}</a></p>',
        *render_topic_list(topics, base_url),
    ]
    return render_document(archive_title(), body, head=head)


def load_topics(posts_dir: Path) -> list[MirrorTopic]:
    """Read all post JSON files and group them into topics."""
    topics: dict[int, MirrorTopic] = {}

    for path in sorted(posts_dir.glob('**/*.json')):
        raw = json.loads(path.read_text())
        post = MirrorPost(raw)
        topic_id = raw['topic_id']

        if topic_id not in topics:
            topics[topic_id] = MirrorTopic(
                id=topic_id,
                slug=raw['topic_slug'],
                title=raw['topic_title'],
            )
        topics[topic_id].posts.append(post)

    for topic in topics.values():
        topic.posts.sort(key=lambda p: p.post_number)

    return list(topics.values())


def main() -> None:
    target_dir = args().target_dir
    target_dir = Path(target_dir) if not isinstance(target_dir, Path) else target_dir
    output_dir = args().output_dir
    output_dir = Path(output_dir) if not isinstance(output_dir, Path) else output_dir

    posts_dir = target_dir / 'posts'
    if not posts_dir.is_dir():
        log.error("no posts directory found at %s", posts_dir)
        raise SystemExit(1)

    base_url = args().url.rstrip('/')

    categories = load_categories(target_dir / 'categories.json')
    metadata = load_topic_metadata(target_dir / 'topics')
    if metadata:
        log.info("found metadata for %d topics and %d categories",
                 len(metadata), len(categories))
    else:
        log.warning("no topic metadata found under %s; the mirror won't show "
                    "categories, tags or view counts (run "
                    "`discourse-archive --backfill-topics`)",
                    target_dir / 'topics')

    topics = load_topics(posts_dir)
    if not topics:
        log.warning("no posts found under %s", posts_dir)
        return

    for topic in topics:
        topic.meta = metadata.get(topic.id, {})
        topic.category = categories.get(topic.meta.get('category_id'))

    # Most recently active topic first.
    topics.sort(key=lambda t: t.last_activity, reverse=True)

    output_dir.mkdir(parents=True, exist_ok=True)
    write_stylesheet(output_dir, categories)

    uploads_dir = target_dir / 'uploads'
    uploads = load_uploads(uploads_dir)
    if uploads:
        log.info("found %d archived uploads in %s", len(uploads), uploads_dir)
    else:
        log.warning("no archived uploads found in %s; images will point at the "
                    "source site (run `discourse-archive --backfill-uploads`)",
                    uploads_dir)
    missing_uploads: set[str] = set()

    for topic in topics:
        full_path = output_dir / topic.filename
        log.info("rendering topic %s (%s) to %s", topic.id, topic.slug, full_path)
        full_path.write_text(render_topic(topic, base_url, uploads, missing_uploads))

    if missing_uploads:
        log.warning("%d referenced uploads are not archived; those images point "
                    "at the source site", len(missing_uploads))
        log.debug("missing uploads: %s", ' '.join(sorted(missing_uploads)))

    if uploads:
        copied = copy_uploads(uploads_dir, output_dir)
        log.info("copied %d new/changed uploads to %s", copied, output_dir / 'uploads')

    index_path = output_dir / 'index.html'
    log.info("writing index with %d topics to %s", len(topics), index_path)
    index_path.write_text(render_index(topics, base_url))


if __name__ == "__main__":
    main()
