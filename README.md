# Author Outreach — Prospect Intelligence System

A public-data author research system for a book-marketing business targeting
romantasy / series-fiction indie authors (US/UK market). It **discovers,
cross-references and qualifies authors** — it never sends messages. You review
each profile and draft the personalized outreach yourself.

## Quickstart — the dashboard

```bash
cd author-outreach
pip install -r requirements.txt   # requests + PyYAML only
python3 server.py                 # → http://localhost:8000
```

Then: **Crawl** tab → pick a platform from the dropdown → **Start crawl** →
watch profiles arrive live → **Leads** tab → open a profile → use the check
links + type review counts → write your draft in **Your notes** → set status.

CLI (same engine, no browser):

```bash
python3 run_discovery.py          # crawl every enabled platform + export
python3 run_discovery.py --source bluesky
python3 run_discovery.py --list   # show all platforms & their status
```

## Platforms (all free / public data only)

| Platform | What it gives us | Status |
|---|---|---|
| **Bluesky** | profiles, bios, links, posts, posting frequency | ✅ working |
| **Reddit** | author subreddits — launch questions, pain points | ✅ working |
| **Royal Road** | serialized fantasy/romantasy — followers, **ratings count**, publish date (JSON-LD) | ✅ working |
| **Booksie** | newest genre postings via sitemap — reads/likes/comments | ✅ working |
| **My Book Cave** | promo-listed books — author, genre, content rating, retailer, date | ✅ working |
| **Smashwords** | public book/search pages, author pages, genre hits | ✅ working |
| **AllAuthor** | public author directory and profiles | ✅ working |
| **Reedsy Discovery** | public discovery pages and book listings | ✅ working |
| **Wattpad** | public stories and author profile pages | ✅ working |
| Book Commentary | — | ⛔ dead / not a valid crawl target |
| Facebook / Instagram / Threads / Amazon / Goodreads | — | deliberately excluded (ban/ToS risk) |

## The workflow the dashboard supports

1. **Crawl** — one platform at a time, selected from the dropdown, live log.
2. **Leads** — filter by platform / tier / your criteria / status / search.
   Criteria flags: **0–50 reviews · just launched · not yet popular ·
   weak advertising content** (✓ / ✗ / ? = unknown yet).
3. **Author profile** — everything in one place:
   - identities across platforms (spotted-count, last seen)
   - books with direct source listing links, genre, popularity, ratings,
     **Amazon/Goodreads check links**, and manual review-count fields
   - publicly listed email addresses and author/contact websites, each linked
     to the page where it was found
   - activity (last post, posts/month), detected marketing gaps,
     suggested outreach angle, source-tagged evidence posts
   - **Your notes** — the draft message, private, never auto-sent
   - status pipeline: new → reviewing → messaged → replied → won/lost/skip
4. **Matches** — same pen name on two platforms → suggested merge; you confirm
   or reject with one click (same handle = merged automatically).

## Scoring (0–100)

Romantasy-specific genre match +10 · author identity +8 · debut/launch
language +20 · series author +15 · pain language +5 each (max 15) · own
website +5 · recent activity up to +15 · posting frequency up to +10.
**Hot ≥ 60 · Warm 40–59 · Cool < 40.**

Gaps detected: publicly struggling with sales · debut with no launch system ·
no email capture · no author website · no links in bio · low posting cadence ·
inactive 30+ days. Each maps to a service you can pitch — the profile shows
the suggested angle.

## Files

```
author-outreach/
├── server.py                # dashboard (stdlib only) → python3 server.py
├── static/index.html        # the dashboard UI
├── run_discovery.py         # CLI crawler
├── config.yaml              # platforms, limits, ALL scoring keywords
├── pipeline/
│   ├── db.py                # SQLite: authors, identities, books, posts, matches
│   ├── scoring.py           # signals, heat score, gaps, criteria evaluation
│   ├── matching.py          # cross-platform suggested matches
│   ├── crawler.py           # background crawl manager (used by server + CLI)
│   ├── report.py            # leads.csv + leads_report.md exports
│   └── sources/             # one adapter per platform (dropdown source)
└── data/
    ├── prospects.db         # everything, source-tagged
    ├── leads.csv            # spreadsheet export
    └── leads_report.md      # daily ranked briefing
```

## Etiquette & compliance (built in)

Public data only · robots.txt respected · polite crawl delays (Smashwords'
4s rule noted for the future adapter) · no logged-in scraping · no messaging
of any kind · rate-limit backoff · opt-outs respected when you outreach
manually.

Public author emails and author-controlled websites are extracted from
profiles/posts and checked on a bounded number of pages, subject to each
site's `robots.txt`. Contact details retain their source URL. CSV exports
include public emails, websites, and book listing URLs; no messages are sent.

## Roadmap

- Headless-browser adapters for Smashwords / AllAuthor / Reedsy (deferred)
- Optional scheduled daily crawls (cron on a free tier or your own machine)
- Export packs (CSV per status, briefing per platform)
