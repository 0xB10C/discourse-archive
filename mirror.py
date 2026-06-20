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
import functools
import datetime
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


# Minimal CSS: a centered, responsive column with a sans-serif font.
_STYLE = (
    '<style>'
    'body{font-family:system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;'
    'max-width:46rem;margin:0 auto;padding:1rem;line-height:1.5;}'
    'img{max-width:100%;height:auto;}'
    'pre{overflow-x:auto;}'
    # Discourse lightbox chrome: the caption bar carries unsized <svg> icons
    # that, without Discourse's CSS, fall back to the 300x150 default and leave
    # a big gap under each image. It is only useful for the JS lightbox.
    '.lightbox-wrapper .meta{display:none;}'
    'svg.d-icon{width:1em;height:1em;}'
    # Onebox (rich link preview) styling, approximating Discourse's look: a
    # bordered card with a small source header, a right-floated thumbnail, and
    # a title + excerpt.
    'aside.onebox{border:1px solid #e0e0e0;border-radius:.25rem;'
    'padding:.75rem 1rem;margin:1rem 0;overflow:hidden;}'
    'aside.onebox .source{font-size:.85em;color:#666;margin-bottom:.5rem;}'
    'aside.onebox .source .site-icon{width:1em;height:1em;'
    'vertical-align:text-bottom;margin-right:.35em;}'
    'aside.onebox .onebox-body{overflow:hidden;}'
    'aside.onebox .onebox-body h3,aside.onebox .onebox-body h4{margin:.2em 0;'
    'font-size:1.05em;}'
    'aside.onebox .onebox-body p{margin:.4em 0;}'
    'aside.onebox .aspect-image,aside.onebox .onebox-body img.thumbnail{'
    'float:right;max-width:25%;height:auto;margin:0 0 .5rem 1rem;}'
    'a.inline-onebox{text-decoration:none;}'
    # GitHub-blob oneboxes wrap an <ol class="lines"> in a <pre>, whose literal
    # newlines/indentation render as blank lines without Discourse's CSS. Reset
    # the pre's whitespace and render the list as a line-numbered code block.
    'pre.onebox{white-space:normal;margin:.5rem 0;}'
    'pre.onebox ol.lines{list-style:none;margin:0;padding:.5rem;'
    'font-family:monospace;background:#f6f8fa;border-radius:.25rem;'
    'overflow-x:auto;}'
    'pre.onebox ol.lines li{counter-increment:li-counter;white-space:pre;}'
    'pre.onebox ol.lines li::before{content:counter(li-counter);'
    'display:inline-block;width:3em;margin-right:1em;color:#999;'
    'text-align:right;}'
    'footer.build{margin-top:3rem;padding-top:1rem;border-top:1px solid #eee;'
    'font-size:.85em;color:#888;text-align:center;}'
    '</style>'
)


def render_build_footer() -> str:
    today = datetime.datetime.now().isoformat()
    return f'<footer class="build">Mirror built {today}</footer>'


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
    def cooked(self) -> str:
        return self.raw.get('cooked') or ''

    @property
    def post_url(self) -> str:
        return self.raw.get('post_url') or ''

    @property
    def reply_to_post_number(self) -> int | None:
        return self.raw.get('reply_to_post_number')

    def get_created_at(self) -> datetime.datetime:
        return datetime.datetime.fromisoformat(self.raw['created_at'])

    def get_updated_at(self) -> datetime.datetime:
        return datetime.datetime.fromisoformat(
            self.raw.get('updated_at') or self.raw['created_at'])


@dataclass
class MirrorTopic:
    id: int
    slug: str
    title: str
    posts: list[MirrorPost] = field(default_factory=list)

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


def render_topic(topic: MirrorTopic, base_url: str) -> str:
    """Render a single topic (with all its posts) to an HTML document."""
    title = html.escape(topic.title)
    description = html.escape(extract_description(topic.posts[0]))
    host = html.escape(source_host())
    site_name = html.escape(f"Archive of {source_host()}")
    canonical = html.escape(f"{base_url}/t/{topic.slug}/{topic.id}")
    og_url = html.escape(site_url_for(topic.filename) or f"{base_url}/t/{topic.slug}/{topic.id}")
    parts = [
        '<!DOCTYPE html>',
        '<html lang="en">',
        '<head>',
        '<meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        _STYLE,
        f'<title>{title}</title>',
        f'<link rel="canonical" href="{canonical}">',
        f'<meta property="og:title" content="{title}">',
        f'<meta property="og:description" content="{description}">',
        '<meta property="og:type" content="article">',
        f'<meta property="og:site_name" content="{site_name}">',
        f'<meta property="og:url" content="{og_url}">',
        '</head>',
        '<body>',
        '<p><a href="index.html">&larr; index</a></p>',
        f'<h1>{title}</h1>',
        f'<p>An archive of <a href="{html.escape(base_url)}">{host}</a> '
        f'&middot; <a href="{canonical}">view original topic &rarr;</a></p>',
    ]

    for post in topic.posts:
        meta = [
            f'<strong>{html.escape(post.author)}</strong>',
            f'<a href="{base_url}{html.escape(post.post_url)}">'
            f'#{post.post_number}</a>',
            f'<time>{html.escape(post.raw["created_at"])}</time>',
        ]
        if post.reply_to_post_number:
            meta.append(
                f'<a href="#post-{post.reply_to_post_number}">'
                f'in reply to #{post.reply_to_post_number}</a>')

        parts.append(f'<article id="post-{post.post_number}">')
        parts.append('<p>' + ' &middot; '.join(meta) + '</p>')
        parts.append(rewrite_links(post.cooked, base_url))
        parts.append('</article>')

    parts += [render_build_footer(), '</body>', '</html>', '']
    return '\n'.join(parts)


def render_index(topics: list[MirrorTopic]) -> str:
    """Render the index page listing topics, most recently active first."""
    heading = html.escape(f"Archive of {source_host()}")
    og_url = site_url_for('index.html')
    parts = [
        '<!DOCTYPE html>',
        '<html lang="en">',
        '<head>',
        '<meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        _STYLE,
        f'<title>{heading}</title>',
        f'<meta property="og:title" content="{heading}">',
        '<meta property="og:type" content="website">',
        f'<meta property="og:site_name" content="{heading}">',
    ]
    if og_url:
        parts.append(f'<meta property="og:url" content="{html.escape(og_url)}">')
    parts += [
        '</head>',
        '<body>',
        f'<h1>{heading}</h1>',
        '<ul>',
    ]

    for topic in topics:
        n = len(topic.posts)
        plural = 'post' if n == 1 else 'posts'
        parts.append(
            f'<li><a href="{html.escape(topic.filename)}">'
            f'{html.escape(topic.title)}</a> '
            f'&mdash; {html.escape(topic.author)}, '
            f'{topic.last_activity.date()} ({n} {plural})</li>')

    parts += ['</ul>', render_build_footer(), '</body>', '</html>', '']
    return '\n'.join(parts)


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

    topics = load_topics(posts_dir)
    if not topics:
        log.warning("no posts found under %s", posts_dir)
        return

    # Most recently active topic first.
    topics.sort(key=lambda t: t.last_activity, reverse=True)

    output_dir.mkdir(parents=True, exist_ok=True)

    for topic in topics:
        full_path = output_dir / topic.filename
        log.info("rendering topic %s (%s) to %s", topic.id, topic.slug, full_path)
        full_path.write_text(render_topic(topic, base_url))

    index_path = output_dir / 'index.html'
    log.info("writing index with %d topics to %s", len(topics), index_path)
    index_path.write_text(render_index(topics))


if __name__ == "__main__":
    main()
