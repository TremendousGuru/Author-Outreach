"""Platform adapter registry — this is what feeds the crawl dropdown.

Status values:
  ok        = built and verified working
  unverified= code shipped, not yet verified from this network
  deferred  = site is JS-rendered; needs a headless browser (future upgrade)
  blocked   = site blocks bots entirely
"""

REGISTRY = {
    "bluesky": {
        "label": "Bluesky", "built": True, "status": "ok",
        "group": "Social", "note": "Public API — profiles, bios, links, posts",
    },
    "reddit": {
        "label": "Reddit", "built": True, "status": "ok",
        "group": "Communities",
        "note": "Author subreddits (r/selfpublish, r/romanceauthors…)",
    },
    "royalroad": {
        "label": "Royal Road", "built": True, "status": "ok",
        "group": "Serialization",
        "note": "Serialized fantasy/romantasy — followers, ratings, new fiction",
    },
    "booksie": {
        "label": "Booksie", "built": True, "status": "ok",
        "group": "Writing community",
        "note": "Newest postings via sitemap — reads, likes, comments",
    },
    "mybookcave": {
        "label": "My Book Cave", "built": True, "status": "ok",
        "group": "Promo deals",
        "note": "Promo-listed books — author, genre, retailer, content rating",
    },
    "smashwords": {
        "label": "Smashwords", "built": False, "status": "deferred",
        "group": "Store", "note": "Site is now JS-rendered — needs headless browser (roadmap)",
    },
    "allauthor": {
        "label": "AllAuthor", "built": False, "status": "deferred",
        "group": "Directory", "note": "Directory is JS-rendered — needs headless browser (roadmap)",
    },
    "reedsy": {
        "label": "Reedsy Discovery", "built": False, "status": "deferred",
        "group": "Discovery", "note": "JS-rendered — needs headless browser (roadmap)",
    },
    "bookcommentary": {
        "label": "Book Commentary", "built": False, "status": "blocked",
        "group": "Reviews", "note": "Blocks bots (403) — manual browsing only",
    },
}


def get_adapter(key):
    if key == "bluesky":
        from pipeline.sources import bluesky
        return bluesky
    if key == "reddit":
        from pipeline.sources import reddit
        return reddit
    if key == "royalroad":
        from pipeline.sources import royalroad
        return royalroad
    if key == "booksie":
        from pipeline.sources import booksie
        return booksie
    if key == "mybookcave":
        from pipeline.sources import mybookcave
        return mybookcave
    raise KeyError(f"no adapter for {key}")
