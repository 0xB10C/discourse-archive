#!/usr/bin/env python3
"""
This script does a basic archive of Discourse content by way of its API.

TODO: figure out how to handle post updates.

"""
import argparse
import urllib.error
import urllib.request
import sys
import re
import time
import os
import json
import hashlib
import functools
import datetime
from dataclasses import dataclass
from pathlib import Path

import logging

loglevel = 'DEBUG' if os.environ.get('DEBUG') else 'INFO'
try:
    # If `rich` is installed, use pretty logging.
    from rich.logging import RichHandler
    logging.basicConfig(level=loglevel, datefmt="[%X]", handlers=[RichHandler()])
except ImportError:
    logging.basicConfig(level=loglevel)

log = logging.getLogger('archive')


parser = argparse.ArgumentParser(
    'discourse-archive',
    description='Create a basic content archive from a Discourse installation')
parser.add_argument(
    '-u', '--url', help='URL of the Discourse server',
    default=os.environ.get('DISCOURSE_URL', 'https://delvingbitcoin.org'))
parser.add_argument(
    '--debug', action='store_true', default=os.environ.get('DEBUG'))
parser.add_argument(
    '-t', '--target-dir', help='Target directory for the archive',
    default=Path(os.environ.get('TARGET_DIR', './archive')))
parser.add_argument(
    '--no-uploads', action='store_true',
    help="Don't download the files (images) uploaded to the Discourse site that "
    "newly archived posts reference")
parser.add_argument(
    '--backfill-uploads', action='store_true',
    help='Download any uploads referenced by already-archived posts that are '
    'missing from <target-dir>/uploads, then exit without syncing posts')


@functools.cache
def args():
    return parser.parse_args()


def http_get(path) -> str:
    log.debug("HTTP GET %s", path)
    backoff = 3

    while True:
        try:
            with urllib.request.urlopen(f"{args().url}{path}") as f:
                return f.read().decode()
        except Exception:
            time.sleep(backoff)
            backoff *= 2

            if backoff >= 256:
                log.exception('ratelimit exceeded, or something else wrong?')
                sys.exit(1)


def http_get_json(path) -> dict:
    try:
        return json.loads(http_get(path))
    except json.JSONDecodeError:
        log.warning("unable to decode JSON response from %r", path)
        raise


# Matches the URL of a file uploaded to Discourse, as referenced from a post's
# `cooked` HTML (in `src`, `srcset`, `href` or `data-download-href`), e.g.
#
#   https://example.org/uploads/default/original/2X/8/<sha1>.png
#   https://example.org/uploads/default/optimized/2X/8/<sha1>_2_690x345.png
#   https://example.org/uploads/default/<sha1>
#
# Every variant of an upload embeds the 40-hex SHA-1 of the *original* file,
# so that's what the archived copy is keyed on: all variants map to one file.
# The host is optional so root-relative and protocol-relative URLs match too.
#
# Keep in sync with the copy in mirror.py.
UPLOAD_URL_RE = re.compile(
    r'(?:https?:)?(?://[^/"\s]+)?/uploads/(?P<db>[^/"\s]+)/'
    r'(?:(?P<kind>original|optimized)/\dX/(?:[0-9a-f]/)*)?'
    r'(?P<sha1>[0-9a-f]{40})'
    r'(?:_\d+_\d+x\d+)?'
    r'(?:\.(?P<ext>[A-Za-z0-9]+))?')

_CONTENT_TYPE_EXT = {
    'image/png': 'png',
    'image/jpeg': 'jpeg',
    'image/gif': 'gif',
    'image/webp': 'webp',
    'image/avif': 'avif',
    'image/svg+xml': 'svg',
}


def find_uploads(cooked: str) -> dict[str, str]:
    """Map sha1 -> URL to fetch the original from, for every upload in `cooked`.

    The URL of the `original` variant is preferred when the post references
    it. Otherwise (only an `optimized` thumbnail or an extension-less download
    link is present) we fall back to Discourse's `/uploads/<db>/<sha1>` route,
    which serves the original for any upload given its hash.
    """
    base = args().url.rstrip('/')
    found: dict[str, str] = {}
    for m in UPLOAD_URL_RE.finditer(cooked):
        sha1 = m.group('sha1')
        if m.group('kind') == 'original':
            url = m.group(0)
            if url.startswith('//'):
                url = f'https:{url}'
            elif url.startswith('/'):
                url = f'{base}{url}'
            found[sha1] = url
        elif sha1 not in found:
            found[sha1] = f"{base}/uploads/{m.group('db')}/{sha1}"
    return found


def http_get_bytes(url: str) -> tuple[bytes, str] | None:
    """GET `url`, returning (body, content-type).

    Unlike `http_get`, a failure here is never fatal: a client error (the
    upload was deleted, or is restricted) returns None right away, anything
    else is retried a few times before giving up with None.
    """
    log.debug("HTTP GET %s", url)
    backoff = 3
    for attempt in range(4):
        try:
            with urllib.request.urlopen(url, timeout=60) as f:
                return f.read(), f.headers.get_content_type()
        except urllib.error.HTTPError as e:
            if 400 <= e.code < 500 and e.code != 429:
                log.warning("%s: HTTP %d, skipping", url, e.code)
                return None
            log.warning("%s: HTTP %d (attempt %d)", url, e.code, attempt + 1)
        except Exception as e:
            log.warning("%s: %s (attempt %d)", url, e, attempt + 1)
        time.sleep(backoff)
        backoff *= 2
    log.warning("%s: giving up", url)
    return None


def existing_uploads(uploads_dir: Path) -> set[str]:
    """The sha1s of the uploads already archived (files are named `<sha1>.<ext>`)."""
    return {p.stem for p in uploads_dir.iterdir() if p.is_file()}


def fetch_uploads(uploads: dict[str, str], uploads_dir: Path, existing: set[str]) -> None:
    """Download the given {sha1: url} uploads that aren't archived yet.

    Each file is saved as `<uploads_dir>/<sha1>.<ext>`, with the extension
    derived from the response's content type. The body's hash is checked
    against the sha1 in the URL. A mismatch is only tolerated (with a warning)
    when the server did return an image: Discourse occasionally serves a file
    that differs from the hash it was registered under (seen with SVGs it
    re-hosts for oneboxes). Anything else, e.g. an error page served with a
    200, is not saved, so it's retried on a later run.
    """
    for sha1, url in uploads.items():
        if sha1 in existing:
            continue

        result = http_get_bytes(url)
        if result is None:
            continue
        body, content_type = result

        if hashlib.sha1(body).hexdigest() != sha1:
            if content_type not in _CONTENT_TYPE_EXT:
                log.warning("upload %s: content doesn't hash to its sha1 and isn't "
                            "an image (got %s, %d bytes), not saving",
                            url, content_type, len(body))
                continue
            log.warning("upload %s: content doesn't hash to its sha1, saving anyway "
                        "since the server returned an image (%s, %d bytes)",
                        url, content_type, len(body))

        ext = _CONTENT_TYPE_EXT.get(content_type)
        if not ext:
            m = UPLOAD_URL_RE.match(url)
            ext = (m and m.group('ext')) or 'bin'

        path = uploads_dir / f'{sha1}.{ext}'
        log.info("saving upload %s (%d bytes) to %s", url, len(body), path)
        path.write_bytes(body)
        existing.add(sha1)
        time.sleep(0.2)


def backfill_uploads(posts_dir: Path, uploads_dir: Path) -> None:
    """Fetch every upload referenced by the archived posts that we don't have yet."""
    uploads: dict[str, str] = {}
    n_posts = 0
    for path in sorted(posts_dir.glob('**/*.json')):
        n_posts += 1
        cooked = json.loads(path.read_text()).get('cooked') or ''
        for sha1, url in find_uploads(cooked).items():
            # Prefer a direct `original` URL over the by-hash fallback route.
            if sha1 not in uploads or '/original/' in url:
                uploads[sha1] = url

    existing = existing_uploads(uploads_dir)
    missing = {s: u for s, u in uploads.items() if s not in existing}
    log.info("%d posts reference %d uploads, %d already archived, fetching %d",
             n_posts, len(uploads), len(uploads) - len(missing), len(missing))
    fetch_uploads(missing, uploads_dir, existing)
    log.info("done: %d uploads archived in %s", len(existing_uploads(uploads_dir)), uploads_dir)


class PostSlug:
    @classmethod
    def id_from_filename(cls, name: str) -> int:
        return int(name.split('-', 1)[0])


@dataclass(frozen=True)
class PostTopic:
    id: int
    slug: str
    title: str


@dataclass(frozen=True)
class Post:
    id: int
    slug: str
    raw: dict

    def get_created_at(self) -> datetime.datetime:
        return datetime.datetime.fromisoformat(self.raw['created_at'])

    def save(self, dir: Path):
        """Write the raw post to disk."""
        idstr = str(self.id).zfill(10)
        filename = f"{idstr}-{self.raw['username']}-{self.raw['topic_slug']}.json"
        folder_name = self.get_created_at().strftime('%Y-%m-%B')
        full_path = dir / folder_name / filename
        full_path.parent.mkdir(parents=True, exist_ok=True)
        log.info("saving post %s to %s", self.id, full_path)
        full_path.write_text(json.dumps(self.raw, indent=2))

    def get_topic(self) -> PostTopic:
        return PostTopic(
            id=self.raw['topic_id'],
            slug=self.raw['topic_slug'],
            title=self.raw['topic_title'],
        )

    @classmethod
    def from_json(cls, j: dict) -> 'Post':
        return cls(
            id=j['id'],
            slug=j['topic_slug'],
            raw=j,
        )


@dataclass(frozen=True)
class Topic:
    id: int
    slug: str
    raw: dict
    markdown: str

    def get_created_at(self) -> datetime.datetime:
        return datetime.datetime.fromisoformat(self.raw['created_at'])

    def save_rendered(self, dir: Path):
        """Write the rendered (.md) topic to disk."""
        date = str(self.get_created_at().date())
        filename = f"{date}-{self.slug}-id{self.id}.md"
        folder_name = self.get_created_at().strftime('%Y-%m-%B')
        full_path = dir / folder_name / filename
        full_path.parent.mkdir(parents=True, exist_ok=True)
        log.info("saving topic markdown %s to %s", self.id, full_path)
        markdown = f"# {self.raw['title']}\n\n{self.markdown}"
        full_path.write_text(markdown)

    def get_topic(self) -> PostTopic:
        return PostTopic(
            id=self.raw['topic_id'],
            slug=self.raw['topic_slug'],
            title=self.raw['topic_title'],
        )

    @classmethod
    def from_json(cls, t: dict, markdown: str) -> 'Topic':
        return cls(
            id=t['id'],
            slug=t['slug'],
            raw=t,
            markdown=markdown,
        )


def main() -> None:
    """
    Sync posts back to `metdata[last_sync_date] - 1 day`, and then save the rendered
    version of all topics associated with those posts.
    """
    target_dir = args().target_dir
    target_dir = Path(target_dir) if not isinstance(target_dir, Path) else target_dir

    (posts_dir := target_dir / 'posts').mkdir(parents=True, exist_ok=True)
    (topics_dir := target_dir / 'rendered-topics').mkdir(parents=True, exist_ok=True)
    (uploads_dir := target_dir / 'uploads').mkdir(parents=True, exist_ok=True)

    if args().backfill_uploads:
        backfill_uploads(posts_dir, uploads_dir)
        return

    archived_uploads = existing_uploads(uploads_dir)

    metadata_file = target_dir / '.metadata.json'
    last_sync_date = None
    metadata = {}

    if metadata_file.exists():
        metadata = json.loads(metadata_file.read_text())
        last_sync_date = datetime.datetime.fromisoformat(metadata['last_sync_date'])

    if last_sync_date:
        # Resync over the last day to catch any post edits.
        last_sync_date -= datetime.timedelta(days=1)

    log.info("detected latest synced post date: %s", last_sync_date)

    topics_to_get = {}
    max_created_at = None
    last_created_at: datetime.datetime | None = None
    last_id: int | None = None

    posts = http_get_json('/posts.json')['latest_posts']
    no_new_posts = False

    while posts:
        log.info("processing %d posts", len(posts))
        for json_post in posts:
            try:
                post = Post.from_json(json_post)
            except Exception:
                log.warning("failed to deserialize post %s", json_post)
                raise
            last_created_at = post.get_created_at()

            if last_sync_date is not None:
                no_new_posts = last_created_at < last_sync_date
                if no_new_posts:
                    break

            post.save(posts_dir)
            if not args().no_uploads:
                fetch_uploads(find_uploads(post.raw.get('cooked') or ''),
                              uploads_dir, archived_uploads)

            if not max_created_at:
                # Set in this way because the first /post.json result returned will be
                # the latest created_at.
                max_created_at = post.get_created_at()

            last_id = post.id
            topic = post.get_topic()
            topics_to_get[topic.id] = topic

        if no_new_posts or last_id is not None and last_id <= 1:
            log.info("no new posts, stopping")
            break

        time.sleep(5)
        posts = http_get_json(
            f'/posts.json?before={last_id}')['latest_posts']

        # Discourse implicitly limits the posts query for IDs between `before` and
        # `before - 50`, so if we don't get any results we have to kind of scan.
        while not posts and last_id >= 0:
            # This is probably off-by-one, but doesn't hurt to be safe.
            last_id -= 49
            posts = http_get_json(
                f'/posts.json?before={last_id}')['latest_posts']
            time.sleep(1)

    if max_created_at is not None:
        metadata['last_sync_date'] = max_created_at.isoformat()
        log.info("writing metadata: %s", metadata)
        metadata_file.write_text(json.dumps(metadata, indent=2))

    time.sleep(3)

    for topic in topics_to_get.values():
        data = http_get_json(f"/t/{topic.id}.json")
        body = http_get(f"/raw/{topic.id}")
        page_num = 2

        if not body:
            log.warning("could not retrieve topic %d markdown", topic.id)
            continue

        while (more_body := http_get(f"/raw/{topic.id}?page={page_num}")):
            body += f"\n{more_body}"

        t = Topic.from_json(data, body)
        t.save_rendered(topics_dir)
        log.info("saved topic %s (%s)", t.id, t.slug)

        time.sleep(0.3)


if __name__ == "__main__":
    main()
