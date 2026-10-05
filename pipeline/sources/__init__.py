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
        "label": "Smashwords", "built": True, "status": "ok",
        "group": "Store", "note": "Public HTML search + book pages; browser fallback is supported if needed",
    },
    "allauthor": {
        "label": "AllAuthor", "built": True, "status": "ok",
        "group": "Directory", "note": "Author directory and public profiles are now reachable through the crawler",
    },
    "reedsy": {
        "label": "Reedsy Discovery", "built": True, "status": "ok",
        "group": "Discovery", "note": "Public discovery pages are included in the active crawl set",
    },
    "wattpad": {
        "label": "Wattpad", "built": True, "status": "ok",
        "group": "Writing community", "note": "Public stories and author pages; no login required for the crawl",
    },
    "bookcommentary": {
        "label": "The Book Commentary", "built": True, "status": "ok",
        "group": "Book reviews", "note": "Public romance and sci-fi/fantasy book reviews and author names",
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
    if key == "smashwords":
        from pipeline.sources import smashwords
        return smashwords
    if key == "allauthor":
        from pipeline.sources import allauthor
        return allauthor
    if key == "reedsy":
        from pipeline.sources import reedsy
        return reedsy
    if key == "wattpad":
        from pipeline.sources import wattpad
        return wattpad
    if key == "bookcommentary":
        from pipeline.sources import bookcommentary
        return bookcommentary
    raise KeyError(f"no adapter for {key}")
