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
usage: discourse-archive [-h] [-u URL] [--debug] [-t TARGET_DIR]

Create a basic content archive from a Discourse installation

options:
  -h, --help            show this help message and exit
  -u URL, --url URL     URL of the Discourse server
  --debug
  -t TARGET_DIR, --target-dir TARGET_DIR
                        Target directory for the archive
```

The structure that it generates looks something like:
```
archive
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
└── 2026-06-18-outbound-connection-success-rates-of-a-bitcoin-node-id142.html
```

Re-running is idempotent - it overwrites the output directory in place, so you
can regenerate the mirror after each sync.
