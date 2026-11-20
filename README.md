# discourse-archive

A script that provides a basic archive of Discourse contents.

## Install

```sh
% pip install discourse-archive
```

or, if you don't trust package managers:

```sh
% curl https://raw.githubusercontent.com/jamesob/discourse-archive/master/archive.py > /on/your/path/discourse-archive
% chmod +x /on/your/path/discourse-archive
```

## Usage

```sh
% discourse-archive --help
usage: discourse-archive [-h] [-u URL] [--debug] [-t TARGET_DIR] [--no-uploads]
                         [--backfill-uploads] [--backfill-topics]

Create a basic content archive from a Discourse installation

options:
  -h, --help            show this help message and exit
  -u URL, --url URL     URL of the Discourse server
  --debug
  -t TARGET_DIR, --target-dir TARGET_DIR
                        Target directory for the archive
  --no-uploads          Don't download the files (images) uploaded to the
                        Discourse site that newly archived posts reference
  --backfill-uploads    Download any uploads referenced by already-archived
                        posts that are missing from <target-dir>/uploads, then
                        exit without syncing posts
  --backfill-topics     Download the topic metadata (category, tags,
                        participants, view count) of already-archived topics
                        that is missing from <target-dir>/topics, then exit
                        without syncing posts
```

The structure that it generates looks something like:
```
archive
├── categories.json
├── uploads
│   ├── 0128f183608738f985c7a22cba2fc9c522f98880.jpeg
│   ├── 455abc133e0ab553eb12218497c96491d2003a1a.png
│   └── 836776ecd335c3cda6bb995651703a4c22997080.png
├── posts
│   ├── 2022-08-August
│   │   ├── 0000000001-system-about-the-meta-category.json
│   │   ├── 0000000046-RubenSomsen-deflationary-money-is-a-good-thing.json
│   │   ├── 0000000047-ajtowns-deflationary-money-is-a-good-thing.json
│   │   └── 0000000048-RubenSomsen-deflationary-money-is-a-good-thing.json
│   ├── 2023-08-August
│   │   ├── 0000000062-jamesob-thoughts-on-scaling-and-consensus-changes-2023.json
│   │   ├── 0000000120-instagibbs-op-vault-fanfiction-for-rate-limited-and-collateralized-unvaulting.json
│   │   ├── 0000000121-instagibbs-op-vault-fanfiction-for-rate-limited-and-collateralized-unvaulting.json
│   │   ├── 0000000143-naumenkogs-proof-of-micro-burn-burning-btc-while-minimizing-on-chain-block-space-usage.json
│   │   ├── 0000000144-RubenSomsen-proof-of-micro-burn-burning-btc-while-minimizing-on-chain-block-space-usage.json
│   │   └── 0000000157-instagibbs-op-vault-fanfiction-for-rate-limited-and-collateralized-unvaulting.json
│   └── 2023-09-September
│       ├── 0000000167-Ajian-thoughts-on-scaling-and-consensus-changes-2023.json
│       ├── 0000000172-jamesob-public-archive-for-delving-bitcoin.json
│       ├── 0000000173-ajtowns-public-archive-for-delving-bitcoin.json
│       ├── 0000000174-jamesob-public-archive-for-delving-bitcoin.json
│       ├── 0000000175-ajtowns-public-archive-for-delving-bitcoin.json
│       └── 0000000178-midnight-public-archive-for-delving-bitcoin.json
├── topics
│   ├── 2022-08-August
│   │   ├── 2022-08-24-about-the-economics-category-id14.json
│   │   └── 2022-08-24-welcome-to-delving-bitcoin-id7.json
│   └── 2023-01-January
│       └── 2023-01-10-lightning-fees-inbound-vs-outbound-id29.json
└── rendered-topics
    ├── 2022-08-August
    │   ├── 2022-08-24-about-the-economics-category-id14.md
    │   ├── 2022-08-24-about-the-implementation-category-id16.md
    │   ├── 2022-08-24-design-for-algorithmic-stablecoin-backed-by-btc-id20.md
    │   ├── 2022-08-24-proof-of-micro-burn-burning-btc-while-minimizing-on-chain-block-space-usage-id21.md
    │   └── 2022-08-24-welcome-to-delving-bitcoin-id7.md
    ├── 2023-01-January
    │   └── 2023-01-10-lightning-fees-inbound-vs-outbound-id29.md
    ├── 2023-08-August
    │   ├── 2023-08-16-thoughts-on-scaling-and-consensus-changes-2023-id32.md
    │   ├── 2023-08-22-op-vault-fanfiction-for-rate-limited-and-collateralized-unvaulting-id55.md
    │   └── 2023-08-23-combined-ctv-apo-into-minimal-txhash-csfs-id60.md
    └── 2023-09-September
        └── 2023-09-05-public-archive-for-delving-bitcoin-id87.md
```

### Topic metadata

Posts carry no more than a `topic_id`, `topic_slug` and `topic_title`;
everything else about the topic they belong to -- its category, tags, view
count, who took part in it and who posted last -- lives on the topic. That
metadata is archived under `<target-dir>/topics`, one JSON file per topic,
named like the rendered markdown of the same topic
(`<created>-<slug>-id<id>.json`). It is the trimmed-down `/t/<id>.json`
response: the topic's own fields plus the participants, without the posts
(archived separately) or the current user's state.

A topic's metadata is a snapshot, so it is re-saved on every sync that sees a
new post in that topic.

The `category_id` it carries is turned into a name and a color by
`<target-dir>/categories.json`, the site's category list with subcategories
flattened into it (each keeping its `parent_category_id`), re-fetched on every
sync.

To fetch the metadata of topics archived before this feature existed, run once:

```sh
% discourse-archive --backfill-topics
```

It fetches the metadata of every archived topic that is missing from
`<target-dir>/topics`, and exits without syncing posts.

### Uploads (images)

Images (and other files) that people upload to Discourse are referenced from
the posts' HTML by URLs like
`https://example.org/uploads/default/original/2X/8/<sha1>.png`. Every variant
of an upload (the original, the resized `optimized/...` thumbnails, the
extension-less download link) embeds the SHA-1 of the original file, so each
upload is archived once as `<target-dir>/uploads/<sha1>.<ext>`, with the
extension taken from the server's content type. The downloaded content is
checked against that hash. A mismatch is logged; it's saved anyway if the
server returned an image (Discourse occasionally serves a file that differs
from the hash it registered it under, seen with SVG onebox icons), but
anything else, e.g. an error page, isn't saved and is retried next time.

Only the original of each upload is fetched, not the resized variants. Uploads
referenced by a post are fetched right after the post is saved, so an
incremental sync also picks up images added when a post was edited. Pass
`--no-uploads` to skip this.

To fetch the uploads for posts archived before this feature existed, run once:

```sh
% discourse-archive --backfill-uploads
```

It scans every archived post, downloads whatever is missing from
`<target-dir>/uploads`, and exits without syncing posts. Uploads that have been
deleted on the source site (HTTP 404) are logged and skipped.

Avatars, emoji images and images hosted on other sites are not archived; the
mirror keeps linking to them where they live.

## Rendering an HTML mirror

Once you have an archive, `mirror.py` renders it into a static HTML site you can
serve anywhere. It reads the per-post JSON under `<target-dir>/posts`, groups the
posts into topics, and writes one HTML page per topic (using Discourse's
server-rendered `cooked` HTML) plus a flat `index.html` listing topics with the
most recently active first, the way Discourse lists them. There is no
external dependency: a page is its HTML plus the mirror's own `style.css`, and
the only script on it is the few lines behind the light/dark toggle.

```sh
% ./mirror.py --help
usage: discourse-mirror [-h] [-u URL] [--debug] [-t TARGET_DIR] [-o OUTPUT_DIR]
                        [-s SITE_URL]

Render a static HTML mirror from a Discourse archive

options:
  -h, --help            show this help message and exit
  -u URL, --url URL     URL of the source Discourse server (used to make
                        relative links in the archived HTML absolute)
  --debug
  -t TARGET_DIR, --target-dir TARGET_DIR
                        Directory of the archive to read
  -o OUTPUT_DIR, --output-dir OUTPUT_DIR
                        Directory to write the rendered site into
  -s SITE_URL, --site-url SITE_URL
                        URL where the mirror itself will be deployed (used for
                        og:url tags). Optional.
```

Typical usage, reading the `./archive` produced above and writing the site into
`./site`:

```sh
% ./mirror.py -t ./archive -o ./site -u https://delvingbitcoin.org
```

The `-u`/`--url` value is used to rewrite root-relative links and images in the
archived HTML (e.g. `/u/alice`, `/uploads/...`) back to absolute URLs on the
source server, so they resolve from wherever you host the mirror. It defaults to
the same `DISCOURSE_URL` environment variable / value as `discourse-archive`, so
make sure it matches the site you archived.

The optional `-s`/`--site-url` (or `SITE_URL` env var) is the public URL where
the rendered mirror will be hosted, e.g. `https://archive.example.org`. When
set, it's used for `og:url` meta tags so social previews link back to the
mirror; if omitted, topic pages fall back to pointing `og:url` at the original
Discourse thread (matching their `rel=canonical`) and the index omits `og:url`
entirely.

The generated structure looks like:
```
site
├── index.html
├── categories.html
├── tags.html
├── style.css
├── c-research-id25.html
├── tag-mempool.html
├── 2025-10-13-about-the-meta-category-id1.html
├── 2025-10-14-about-the-research-category-id25.html
├── 2026-06-18-outbound-connection-success-rates-of-a-bitcoin-node-id142.html
└── uploads
    ├── 0128f183608738f985c7a22cba2fc9c522f98880.jpeg
    └── 455abc133e0ab553eb12218497c96491d2003a1a.png
```

Re-running is idempotent - it overwrites the output directory in place, so you
can regenerate the mirror after each sync.

### The topic list

`index.html` lists topics the way Discourse's own topic list does: the title,
the category and tags under it, the faces of up to five people who posted (the
original poster first and whoever posted last at the end, both marked, with
the most prolific posters in between), the reply count, the view count, and
how long ago the topic was last active.

The category, the tags and the view count come from the archived topic
metadata, so they are only there for an archive that has it -- see
[Topic metadata](#topic-metadata) above and `discourse-archive
--backfill-topics`. Everything else is derived from the archived posts, so a
mirror of an older archive simply lists topics without them.

Reply and view counts are what the source site reported for the topic when it
was last synced, so a topic whose posts aren't all archived still shows how
many replies it really has. The avatars, like emoji, are not archived: they
are loaded from the source site.

### Topic pages

A topic page is its title, the category and tags it is filed under, and its
posts in order, each with its author's avatar, the post number (linking to the
post on the source site), when it was written, and what it replies to.

Under the first post is Discourse's "topic map": when the topic was created
and last replied to, how many replies, views and people it has, and the
avatar of everyone who posted with their post count.

### Browsing by category and tag

The header links to a category list and a tag list, both built from the
archived topic metadata:

- `categories.html` -- a card per category with its description and how many
  of its topics are archived, subcategories listed under their parent
- `c-<slug>-id<id>.html` -- the topics in one category; a parent category's
  page also lists its subcategories' topics, as Discourse's does
- `tags.html` -- every tag in use, most used first
- `tag-<slug>.html` -- the topics carrying one tag

The category badge and the tags under a topic's title link to these pages.
Only categories and tags that archived topics actually use get a page, so
there are no links that lead nowhere; for an archive with no topic metadata
both lists are simply empty.

### Styling

The mirror's look follows Discourse's default theme: the same color roles, a
similar post layout (an avatar gutter next to the author line and body), and
styling for the markup that Discourse's post HTML brings with it -- quoted
posts, oneboxes (rich link previews), @mentions, lightboxed images, tables,
footnotes.

It is all one stylesheet, `style.css`, written into the output directory next
to the pages and regenerated on every run. To restyle the mirror, edit
`STYLESHEET` in `mirror.py`.

Pages come in a light and a dark theme, following Discourse's own two default
color schemes. Which one a viewer gets is their system preference
(`prefers-color-scheme`) unless they pick one with the toggle in the header,
which is remembered (in `localStorage`) for the rest of the mirror. The choice
is applied before the page is painted, so navigating the mirror in dark mode
doesn't flash white.

Both themes are defined as custom properties at the top of the stylesheet --
the same color roles Discourse uses, `--primary` for text, `--secondary` for
the background, `--tertiary` for links -- so a different palette is a matter
of changing those values.

### Images

Uploads archived under `<target-dir>/uploads` (see above) are copied into
`<output-dir>/uploads`, and every reference to them in the posts' HTML (the
`<img src>`, the lightbox's full-size and download links) is rewritten to the
local copy, so the mirror's images keep working if the source site goes away.
Since only the original of each upload is archived, the resized variants and
`srcset` attributes are replaced by the original; the `<img>` keeps its
width/height so the layout is unchanged.

A referenced upload that isn't in the archive (not fetched yet, or deleted on
the source site) is left pointing at the source site, and the mirror logs how
many such references it saw. Run `discourse-archive --backfill-uploads` to
fetch them.

### Missing posts

If a topic has a gap in its post numbers (e.g. posts #14 and #16 are archived
but #15 isn't), the mirror renders an inline warning box between the
surrounding posts calling out the gap, rather than silently skipping it.

A gap usually means one of:
- the post hasn't been archived yet, e.g. `discourse-archive` was interrupted
  or hasn't been re-run since the post was made
- the topic was unlisted/hidden at the time of a previous sync and only made public
  later, so its posts were skipped back then
- the post was deleted or removed by moderation on the source site, in which
  case it's gone for good and re-archiving won't bring it back

Since the archive can't tell these cases apart on its own, running a full
resync is worth doing occasionally. It'll fill in gaps caused by missed or
previously-unlisted posts, and any gap that persists after a resync is likely
deleted/moderated.

`discourse-archive` normally does an incremental sync, only fetching posts
created after `last_sync_date` in `<target-dir>/.metadata.json`. To force a
full resync, delete that file before re-running.

Each warning is preceded by an HTML comment `<!-- MIRROR-MISSING-POST -->`,
so you can grep the rendered site for an overview of how many gaps exist.

```sh
% grep -rl MIRROR-MISSING-POST site/ | wc -l   # topics with at least one gap
% grep -ro MIRROR-MISSING-POST site/*.html | wc -l  # total gaps across the mirror
```
