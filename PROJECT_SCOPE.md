# PROJECT SCOPE — Author Intelligence & Profiling System

**Version:** 1.0 (for your sign-off) · **Date:** 2026-10-03
**Budget constraint:** ₦0 / $0 — free public sources and free tools only.

---

## 1. Objective (one sentence)

Build a **profiling system** that discovers self-published authors across free
platforms, cross-references everything it finds about each author into one
rich profile, flags the ones that match your criteria (0–50 reviews, just
launched, low popularity, weak advertising content), and lets **you** open each
author's profile and personally draft the outreach message — **no automated
messaging of any kind.**

---

## 2. What is IN scope

### 2.1 Platforms (dropdown-indexed; each crawled only when you select it)

| # | Platform | Status | What we collect | Free? |
|---|----------|--------|-----------------|-------|
| 1 | **Bluesky** | ✅ BUILT & TESTED (135+ leads already) | profile, bio, links, recent posts, posting frequency | ✅ |
| 2 | **Reddit** (r/selfpublish, r/romanceauthors, r/fantasywriters…) | ✅ BUILT & TESTED | posts, pain points, launch questions, activity | ✅ |
| 3 | **Smashwords** | ✅ Verified crawlable | book listings by category, **ratings count**, price, author page, genre | ✅ (4s crawl delay per their rules) |
| 4 | **AllAuthor** | ✅ Verified crawlable | author directory, author profiles, books, links to their sites | ✅ |
| 5 | **Booksie** | ✅ Verified (via sitemap) | self-pub books, author portfolios, read/comment counts | ✅ |
| 6 | **My Book Cave** (what you called "BookCave") | ✅ Verified crawlable | promo-listed books, genres, author info | ✅ |
| 7 | **Reedsy Discovery** | ⚠️ Reachable; browse URL changed — verify at build | new indie books + review counts | ✅ |
| 8 | **Royal Road** | ⚠️ Cloudflare may challenge; verify from your machine | serialized fantasy/romantasy, **ratings count, followers**, author pages | ✅ |
| 9 | **Book Commentary** | ❌ Blocks bots (403) | — (manual browsing only, or drop) | — |

**Named corrections found during verification:** `bookcave.com` is a parked ad
domain — the real site is **mybookcave.com**. `bookcommentary.com` actively
blocks bots, so it cannot be crawled even for free; it stays on a manual list
unless we find an alternative route.

**Deliberately excluded (ban risk, agreed earlier):** Facebook, Instagram,
Threads scraping, and any logged-in scraping. **Amazon & Goodreads: no
scraping** (blocked + against their rules) — see the "manual check links"
design below, which keeps us at $0.

### 2.2 The author profile (what you see when you open an author's section)

```
┌──────────────────────────────────────────────────────────────┐
│ AUTHOR: Evelyn Shine          heat score 83/100 🔥 HOT       │
│ Status: [new ▼]  (new / reviewing / messaged / replied /     │
│                   won / lost / skip)                         │
├──────────────────────────────────────────────────────────────┤
│ IDENTITIES (cross-referenced)                                │
│  bluesky: evelynshine.bsky.social — spotted 3× (last: today) │
│  smashwords: evshine — spotted 1× (last: this week)          │
│  reddit: u/evelyn_shine — POSSIBLE MATCH (confirm?) [Y/N]    │
├──────────────────────────────────────────────────────────────┤
│ BOOKS                                                        │
│  • The Librarian's Gargoyle (Bk 1, Stone Awakenings)         │
│    – found on: bluesky bio + smashwords                      │
│    – platform popularity: 12 ratings on Smashwords           │
│    – Amazon reviews: [CHECK LINK →] you type: [__] (0–50 ✓)  │
│    – Goodreads ratings: [CHECK LINK →] you type: [__]        │
│    – genre: sapphic romantasy · published: 2025              │
├──────────────────────────────────────────────────────────────┤
│ ACTIVITY & REACH                                             │
│  last posted 1.6 days ago · ~69 posts/month · 3 platforms    │
│  follower-ish signals where the platform exposes them        │
├──────────────────────────────────────────────────────────────┤
│ MARKETING SIGNALS & GAPS                                     │
│  ✗ no email capture detected                                 │
│  ✗ no own website — only platform links                      │
│  ✗ debut / launch-phase (no ARC team visible)                │
│  ✓ has Patreon (monetization attempt)                        │
│  → Criteria match: reviews 0–50 ✓ · just launched ✓ ·        │
│    low popularity ✓ · weak promo content ✓                   │
├──────────────────────────────────────────────────────────────┤
│ EVIDENCE (raw posts/bios, each source-tagged)                │
│  "…76% OFF The Librarian's Gargoyle…" — bluesky, 18 Sep      │
│  "…debut sapphic novel…" — bluesky bio                       │
├──────────────────────────────────────────────────────────────┤
│ YOUR NOTES / DRAFT MESSAGE (private, never auto-sent)        │
│  [big text box — you write the personalized message here]    │
└──────────────────────────────────────────────────────────────┘
```

### 2.3 Cross-referencing engine (three levels)

1. **Auto-merge** — same handle/username on two platforms → one profile,
   instantly (already working).
2. **Suggested matches** — same pen name + same/similar book title on two
   platforms → queued for **your** confirm/reject in the UI (never merged
   blindly — "Evelyn Shine" on two sites *might* be two people).
3. **Source-tagged evidence** — every bio line, post, book, and metric keeps
   the platform it came from and when it was seen. Nothing is mixed.

### 2.4 Qualification criteria (your rules, built in as filters)

| Criterion | How the system applies it |
|---|---|
| 0–50 reviews | platform-native review/rating counts where available; for Amazon/Goodreads you get one-click search links and type the number in |
| Just launched / just published | publication date where the platform shows it; debut/launch language in posts |
| Not yet popular | low ratings/reads/followers vs. platform norms |
| Weak advertising content | no/weak website, no email capture, thin promo posting, no links |

### 2.5 The interface (local web dashboard, runs in your browser)

- **Crawl page:** dropdown of the indexed platforms (each enabled/disabled in
  config) → select one → click **Crawl** → live progress → new profiles land
  in the database.
- **Leads page:** sortable/filterable table — filter by platform, tier,
  criterion (e.g. "review count ≤ 50 AND launched ≤ 90 days"), status.
- **Profile page:** the full card above, per author.
- **Matches page:** suggested cross-platform merges awaiting your confirm.

---

## 3. What is OUT of scope (agreed boundaries)

- ❌ **No message sending of any kind** — no email engine, no DMs, no
  automation. All outreach is drafted and sent by you personally.
- ❌ **No LLM message drafting** — the system profiles; you write.
- ❌ **No paid APIs or tools** — zero budget, enforced.
- ❌ **No Facebook / Instagram / Threads scraping** — account-ban risk.
- ❌ **No Amazon / Goodreads scraping** — one-click search links instead.
- ❌ **No on-device phone listener** — architecturally parked (agreed).
- ❌ No buying of contact lists, ever.

---

## 4. Expected results / outcome

- **Daily discovery volume (realistic, with polite crawl delays):**
  Bluesky ~25–150, Reddit ~25–50, Smashwords/AllAuthor/Booksie/MyBookCave
  ~50–200 each on fresh crawls (directories are finite — weekly re-crawls
  refresh them). Expect **100–300 new qualified profiles per week** at zero
  cost, compounding in your database.
- **Per author:** one complete, cross-referenced profile with evidence and
  criteria flags, ready for you to write a message that names their book and
  their exact gap.
- **Attribution:** you always know which platform delivered which lead — so
  after a month you know where the best authors hang out.

## 5. Requirements (your side — all free)

1. A computer (Windows/Mac/Linux) with **Python 3** installed — I'll give you
   the exact setup steps, they take ~10 minutes.
2. **~30–60 minutes a day** to run crawls, confirm matches, review profiles,
   and draft your messages.
3. That's it. No accounts, no API keys, no money, no VPS.

## 6. Limits — how far it can go (honest boundaries)

| Limit | Why | Workaround |
|---|---|---|
| Crawl speed | Polite delays (Smashwords requires 4s/page; others ~1–3s) | a platform run takes minutes, not seconds — fine for daily use |
| Amazon/Goodreads review counts | They block scrapers; their ToS forbids it | one-click search link per book; you type the count (15 sec/book) — the $0 trade-off |
| Cloudflare/JS sites (Book Commentary; Royal Road from cloud IPs) | bot protection | verified to work where possible from your home connection; otherwise manual |
| Genre/gap detection accuracy | keyword heuristics (~85% right) | profiles always show the raw bio + posts so you can eyeball before writing |
| Directories are finite | Smashwords/AllAuthor lists don't grow daily | re-crawl weekly; discovery volume then comes mostly from Bluesky/Reddit |
| Scale | SQLite handles tens of thousands of profiles comfortably | beyond that (far future) → bigger DB, still free (PostgreSQL) |
| Legal | public data only, robots.txt respected, no login-walls | this is a feature, not a bug — it's what keeps the system safe |

## 7. How it operates — your daily workflow

1. Open the dashboard in your browser (`localhost:8000` — I start it with one
   command for you).
2. **Select a platform from the dropdown** → click **Crawl** → watch it fill
   the database live.
3. Open **Matches** → confirm/reject suggested cross-platform merges (30
   seconds).
4. Open **Leads** (filtered by your criteria) → work top-down:
   - open a profile → everything about the author is in one place;
   - click the Amazon/Goodreads check links → type the review count;
   - the criteria flags update (0–50 ✓ etc.);
   - write your personalized message in the notes box;
   - set status → next author.
5. Close the laptop. The database keeps everything, including who you've
   already contacted and what you said.

## 8. Build plan (each phase delivered working)

- **Phase A — Dashboard + profiles:** local web UI (dropdown crawl, leads
  table, full profile pages, notes/status, manual review-count fields,
  criteria filters) over the two already-built sources. *← next build*
- **Phase B — New platform adapters:** Smashwords, AllAuthor, Booksie,
  My Book Cave.
- **Phase C — Cross-match engine:** suggested matches + confirm UI; Reedsy
  Discovery & Royal Road verification from your machine.
- **Phase D (optional, later):** scheduled auto-crawls, export packs.

## 9. Decisions I need from you before building Phase A

1. Confirm the platform set (§2.1) — including dropping Book Commentary to
   "manual list" status.
2. Confirm the dashboard (browser-based, dropdown) is what you pictured.
3. Confirm the manual Amazon/Goodreads check-links approach is acceptable at
   zero budget.
4. Confirm auto-merge on handle + confirm-on-name matching (§2.3).
