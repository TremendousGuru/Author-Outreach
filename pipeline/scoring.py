"""Rule-based signal detection, heat scoring, gap detection and outreach angles.

This is the money layer: it turns raw bio/post text into the 3-5 "gaps" that
make each outreach message personal — without anyone reading 100 books a day.
"""
import datetime
import re
from urllib.parse import urlparse

GAP_TEXT = {
    "publicly_struggling_sales": "Publicly struggling with sales",
    "debut_no_launch_system": "Debut / launch-phase — likely no ARC team, email list or launch funnel yet",
    "no_email_capture": "No visible email capture / newsletter",
    "no_own_website": "No author website — only social / platform links",
    "no_links_in_bio": "No links in bio — readers have nowhere to land",
    "low_posting_cadence": "Low posting cadence — no content engine",
    "inactive_30d": "Quiet for 30+ days — audience cooling off",
}

GAP_PITCH = {
    "publicly_struggling_sales": "empathy + free listing/funnel audit",
    "debut_no_launch_system": "Launch Kit (ARC team setup + reader-magnet landing page)",
    "no_email_capture": "reader magnet + newsletter funnel so they own their audience",
    "no_own_website": "author website with universal buy links + email capture",
    "no_links_in_bio": "link hub + author page so readers have somewhere to land",
    "low_posting_cadence": "content system (calendar + templates you build for them)",
    "inactive_30d": "reactivation plan + automated posting system",
}

GAP_PRIORITY = [
    "publicly_struggling_sales",
    "debut_no_launch_system",
    "no_email_capture",
    "no_own_website",
    "no_links_in_bio",
    "low_posting_cadence",
    "inactive_30d",
]

URL_RE = re.compile(r"(?:https?://|www\.)[^\s<>\"')\]]+")

PLATFORM_HOSTS = [
    "patreon.com", "tapas.io", "goodreads.com", "bookbub.com", "instagram.com",
    "twitter.com", "x.com", "tiktok.com", "facebook.com", "youtube.com",
    "youtu.be", "amazon.com", "amazon.co.uk", "amazon.de", "amazon.ca",
    "amazon.com.au", "amzn.to", "a.co", "bit.ly", "tinyurl.com", "linktr.ee",
    "books2read.com", "storyorigin.app", "bookfunnel.com", "ko-fi.com",
    "buymeacoffee.com", "royalroad.com", "wattpad.com", "inkitt.com",
    "reamstories.com", "gumroad.com", "payhip.com", "draft2digital.com",
    "smashwords.com", "kobo.com", "apple.co", "barnesandnoble.com",
    "bookshop.org", "pinterest.com", "discord.gg", "discord.com", "twitch.tv",
    "threads.net", "bsky.app", "mastodon.social", "allauthor.com",
    "google.com", "t.co", "facebook.com", "linkedin.com", "reddit.com",
    "spotify.com", "audiobooks.com", "chirpbooks.com", "hootsuite.com",
    "authorsdirect.com", "booksprout.co", "prolificworks.com",
]

NEWSLETTER_HOSTS = [
    "mailchi.mp", "substack.com", "buttondown.email", "beehiiv.com",
    "kit.com", "convertkit.com", "mailchimp.com", "bookfunnel.com",
    "storyorigin.app",
]

NEWSLETTER_WORDS = [
    "newsletter", "mailing list", "email list", "subscriber", "subscribe",
    "reader magnet", "free short story", "free prequel", "join my list",
    "sign up", "free chapter",
]


def matches(text, keywords):
    if not text:
        return []
    t = text.lower()
    return [k for k in keywords if k in t]


def extract_links(text):
    if not text:
        return []
    out = []
    for u in URL_RE.findall(text):
        u = u.rstrip(".,;:!?'\"")
        if not u.startswith("http"):
            u = "https://" + u
        out.append(u)
    return list(dict.fromkeys(out))


def _host(u):
    try:
        return urlparse(u).netloc.lower().removeprefix("www.")
    except Exception:
        return ""


def classify_links(links):
    platform, own = [], []
    for u in links:
        host = _host(u)
        is_platform = any(host == h or host.endswith("." + h) for h in PLATFORM_HOSTS)
        (platform if is_platform else own).append(u)
    return platform, own


def _parse_ts(ts):
    try:
        return datetime.datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except Exception:
        return None


def analyze(bio_text, posts, cfg):
    """bio_text: str. posts: [{posted_at, text, post_url, platform}] or None.

    Returns {score, gaps, gap_texts, angle, last_post_days, posts_per_month,
             signals, links}.
    """
    scfg = cfg["scoring"]
    posts = posts or []
    combined = " ".join([bio_text or ""] + [p.get("text") or "" for p in posts])
    low = combined.lower()

    signals = {
        "genre_specific": matches(low, scfg["genre_specific"]),
        "genre_broad": matches(low, scfg["genre_broad"]),
        "author": matches(low, scfg["author_keywords"]),
        "debut": matches(low, scfg["debut_keywords"]),
        "series": matches(low, scfg["series_keywords"]),
        "pain": matches(low, scfg["pain_keywords"]),
    }

    links = extract_links(bio_text or "")
    for p in posts:
        links += extract_links(p.get("text") or "")
    links = list(dict.fromkeys(links))[:20]
    platform_links, own_links = classify_links(links)

    score = 0
    if signals["genre_specific"]:
        score += 10
    elif signals["genre_broad"]:
        score += 4
    if signals["author"]:
        score += 8
    if signals["debut"]:
        score += 20
    if signals["series"]:
        score += 15
    score += min(15, 5 * len(signals["pain"]))
    if own_links:
        score += 5

    # ---- activity metrics ----
    last_days = None
    ppm = None
    parsed = [ts for ts in (_parse_ts(p.get("posted_at")) for p in posts) if ts]
    now = datetime.datetime.now(datetime.timezone.utc)
    if parsed:
        latest, oldest = max(parsed), min(parsed)
        last_days = round((now - latest).total_seconds() / 86400, 1)
        window_days = max(1, min(90, (now - oldest).days + 1))
        recent = [d for d in parsed if (now - d).days <= 90]
        ppm = round(len(recent) * 30.0 / window_days, 1)
        if last_days <= 14:
            score += 15
        elif last_days <= 30:
            score += 10
        elif last_days <= 90:
            score += 5
        if ppm >= 8:
            score += 10
        elif ppm >= 4:
            score += 5

    # ---- gap detection ----
    has_newsletter = (any(w in low for w in NEWSLETTER_WORDS)
                      or any(_host(u) and any(_host(u) == h or _host(u).endswith("." + h)
                                             for h in NEWSLETTER_HOSTS) for u in links))

    gaps = []
    if any(k in signals["pain"] for k in
           ["no sales", "slow sales", "not selling", "struggling"]):
        gaps.append("publicly_struggling_sales")
    if signals["debut"]:
        gaps.append("debut_no_launch_system")
    if not has_newsletter:
        gaps.append("no_email_capture")
    if links and not own_links:
        gaps.append("no_own_website")
    if not links:
        gaps.append("no_links_in_bio")
    if ppm is not None and ppm < 4:
        gaps.append("low_posting_cadence")
    if last_days is not None and last_days > 30:
        gaps.append("inactive_30d")
    gaps = [g for g in GAP_PRIORITY if g in gaps]

    if not gaps:
        angle = "Offer a free 15-minute book-page + funnel audit."
    else:
        pitches = [GAP_PITCH[g] for g in gaps[:2]]
        angle = "Lead with: " + pitches[0] + (
            " Then: " + pitches[1] if len(pitches) > 1 else "")

    return {
        "score": score,
        "gaps": gaps,
        "gap_texts": [GAP_TEXT[g] for g in gaps],
        "angle": angle,
        "last_post_days": last_days,
        "posts_per_month": ppm,
        "signals": signals,
        "links": links,
        "own_links": own_links,
    }


def is_prospect(bio_text, cfg):
    """Should this profile even be stored as a prospect?"""
    low = (bio_text or "").lower()
    if matches(low, cfg["scoring"]["exclude_keywords"]):
        return False
    if matches(low, cfg["scoring"]["author_keywords"]):
        return True
    return bool(matches(low, cfg["scoring"]["genre_specific"]))


# ---------------------------------------------------------------------------
# Qualification criteria (the client's four rules)
# ---------------------------------------------------------------------------

def _days_ago(date_str, cutoff_days):
    import datetime
    if not date_str:
        return None
    try:
        d = datetime.datetime.fromisoformat(str(date_str).replace("Z", "+00:00"))
        if d.tzinfo is None:
            d = d.replace(tzinfo=datetime.timezone.utc)
        return (datetime.datetime.now(datetime.timezone.utc) - d).days <= cutoff_days
    except ValueError:
        return None


def evaluate_criteria(books, analysis):
    """Apply the client's qualification rules to one author.

    books: rows from the books table. analysis: dict from analyze().
    Returns flags: True / False / None (= unknown, not enough data yet).
    """
    flags = {
        "reviews_0_50": None,      # has a book with 0-50 reviews
        "just_launched": None,     # published/listed within ~90 days or debut
        "low_popularity": None,    # small audience on the platforms we can see
        "weak_ad_content": False,  # missing website/email capture/links
    }
    known = []
    for b in books:
        for v in (b["amazon_reviews"], b["goodreads_ratings"], b["ratings_count"]):
            if v is not None:
                try:
                    known.append(int(v))
                except (TypeError, ValueError):
                    pass
    if known:
        flags["reviews_0_50"] = min(known) <= 50
        flags["low_popularity"] = min(known) <= 50

    gaps = analysis.get("gaps", []) if analysis else []
    debut = "debut_no_launch_system" in gaps
    recent_book = any(_days_ago(b["pub_date"], 90) for b in books)
    if debut or recent_book:
        flags["just_launched"] = True
    elif books and all(b["pub_date"] and not _days_ago(b["pub_date"], 90) for b in books):
        flags["just_launched"] = False

    weak = {"no_own_website", "no_email_capture", "no_links_in_bio",
            "low_posting_cadence"} & set(gaps)
    flags["weak_ad_content"] = bool(weak)
    return flags


CRITERIA_LABELS = {
    "reviews_0_50": "0–50 reviews/ratings",
    "just_launched": "recently published or debut",
    "low_popularity": "low visible popularity",
    "weak_ad_content": "weak advertising content",
}


def books_meeting_criteria(books, analysis):
    qualified = []
    for book in books:
        flags = evaluate_criteria([book], analysis)
        criteria = [label for key, label in CRITERIA_LABELS.items()
                    if flags[key] is True]
        if criteria:
            qualified.append({"book": book, "criteria": criteria})
    return qualified
