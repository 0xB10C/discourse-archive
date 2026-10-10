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
                         [--backfill-uploads]

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
```

The structure that it generates looks something like:
```
archive
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
posts into topics, and writes one minimal, self-contained HTML page per topic
(using Discourse's server-rendered `cooked` HTML) plus a flat `index.html`
listing topics with the most recently active first.

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
├── 2025-10-13-about-the-meta-category-id1.html
├── 2025-10-14-about-the-research-category-id25.html
├── 2026-06-18-outbound-connection-success-rates-of-a-bitcoin-node-id142.html
└── uploads
    ├── 0128f183608738f985c7a22cba2fc9c522f98880.jpeg
    └── 455abc133e0ab553eb12218497c96491d2003a1a.png
```

Re-running is idempotent - it overwrites the output directory in place, so you
can regenerate the mirror after each sync.

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
