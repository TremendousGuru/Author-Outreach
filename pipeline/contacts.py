"""Extract publicly listed author contacts and check author-controlled sites."""
import html
import ipaddress
import re
import socket
import time
import urllib.parse
import urllib.robotparser
from html.parser import HTMLParser

import requests

from pipeline import db, scoring

USER_AGENT = "AuthorOutreachResearch/1.0 (+public author contact discovery)"
EMAIL_RE = re.compile(r"(?<![\w.+-])[\w.!#$%&'*+/=?^`{|}~-]+@[\w-]+(?:\.[\w-]+)+")
_robots_cache = {}


class _Links(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.hrefs = []

    def handle_starttag(self, tag, attrs):
        if tag.lower() == "a":
            href = dict(attrs).get("href", "")
            if href:
                self.hrefs.append(href)


def _safe_url(url):
    try:
        parsed = urllib.parse.urlsplit(url)
        host = (parsed.hostname or "").lower().rstrip(".")
        if parsed.scheme not in ("http", "https") or not host:
            return None
        if parsed.username or parsed.password or host in ("localhost",) or host.endswith((".local", ".localhost")):
            return None
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            address = None
        if address is not None and not address.is_global:
            return None
        return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, parsed.path or "/",
                                        parsed.query, ""))
    except ValueError:
        return None


def _public_host(url):
    host = urllib.parse.urlsplit(url).hostname
    try:
        addresses = {ipaddress.ip_address(item[4][0])
                     for item in socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)}
    except (socket.gaierror, ValueError):
        return False
    return bool(addresses) and all(address.is_global for address in addresses)


def _emails(text):
    decoded = html.unescape(text or "")
    found = {email.rstrip(".,;:").lower() for email in EMAIL_RE.findall(decoded)}
    for address in re.findall(r"(?i)mailto:([^\s\"'<>?]+)", decoded):
        address = urllib.parse.unquote(address).split("?", 1)[0].strip().lower()
        if EMAIL_RE.fullmatch(address):
            found.add(address)
    return sorted(found)


def _robots_allows(url):
    parsed = urllib.parse.urlsplit(url)
    origin = f"{parsed.scheme}://{parsed.netloc}"
    if origin not in _robots_cache:
        robots_url = origin + "/robots.txt"
        try:
            response = requests.get(robots_url, headers={"User-Agent": USER_AGENT},
                                    timeout=8, allow_redirects=False)
            parser = urllib.robotparser.RobotFileParser(robots_url)
            if response.status_code in (404, 410):
                parser.parse([])
            elif response.status_code == 200:
                parser.parse(response.text.splitlines())
            else:
                _robots_cache[origin] = None
                return False
            _robots_cache[origin] = parser
        except requests.RequestException:
            _robots_cache[origin] = None
            return False
    parser = _robots_cache[origin]
    return bool(parser and parser.can_fetch(USER_AGENT, url))


def _contact_kind(url):
    parsed = urllib.parse.urlsplit(url)
    host = (parsed.hostname or "").lower()
    path = parsed.path.lower()
    if any(host == h or host.endswith("." + h) for h in scoring.NEWSLETTER_HOSTS):
        return "newsletter"
    if any(part in path for part in ("contact", "about", "impressum")):
        return "contact_page"
    return "website"


def _save_text_contacts(conn, author_id, text, source_url, platform):
    for email in _emails(text):
        db.upsert_contact(conn, author_id, "email", email, source_url, platform)
    links = scoring.extract_links(text)
    for match in re.findall(r"(?i)mailto:([^\s\"'<>?]+)", text or ""):
        email = urllib.parse.unquote(match).split("?", 1)[0].strip().lower()
        if EMAIL_RE.fullmatch(email):
            db.upsert_contact(conn, author_id, "email", email, source_url, platform)

    owned = []
    for link in links:
        if not scoring.classify_links([link])[1]:
            continue
        safe = _safe_url(link)
        if not safe:
            continue
        kind = _contact_kind(safe)
        is_new = db.upsert_contact(conn, author_id, kind, safe, source_url, platform)
        if is_new and kind in ("website", "contact_page"):
            owned.append(safe)
    return owned


def _fetch_site_contacts(conn, author_id, website, source_platform, max_pages, delay):
    queue = [website]
    checked, seen = 0, set()
    host = urllib.parse.urlsplit(website).hostname
    while queue and checked < max_pages:
        url = _safe_url(queue.pop(0))
        if not url or url in seen or urllib.parse.urlsplit(url).hostname != host:
            continue
        seen.add(url)
        if not _public_host(url) or not _robots_allows(url):
            continue
        if delay:
            time.sleep(delay)
        try:
            response = requests.get(url, headers={"User-Agent": USER_AGENT},
                                    timeout=8, allow_redirects=False)
            if response.status_code != 200 or "html" not in response.headers.get("Content-Type", "").lower():
                continue
        except requests.RequestException:
            continue
        checked += 1
        page = response.text[:1_000_000]
        for email in _emails(page):
            db.upsert_contact(conn, author_id, "email", email, url, source_platform)
        parser = _Links()
        try:
            parser.feed(page)
        except Exception:
            continue
        if checked == 1:
            for href in parser.hrefs:
                candidate = _safe_url(urllib.parse.urljoin(url, html.unescape(href)))
                path = urllib.parse.urlsplit(candidate or "").path.lower()
                if (candidate and urllib.parse.urlsplit(candidate).hostname == host
                        and any(term in path for term in ("contact", "about", "impressum"))):
                    kind = _contact_kind(candidate)
                    db.upsert_contact(conn, author_id, kind, candidate, url, source_platform)
                    queue.append(candidate)
    return checked


def enrich_author(conn, author_id, max_site_pages=4, max_sites=2, delay=0.8):
    """Save contacts from public bios/posts and check newly discovered own sites."""
    sources = []
    for identity in conn.execute(
            "SELECT platform, platform_url, bio FROM identities WHERE author_id=?",
            (author_id,)):
        sources.append((identity["bio"], identity["platform_url"], identity["platform"]))
    for post in db.get_posts(conn, author_id):
        sources.append((post["text"], post["post_url"], post["platform"]))

    new_sites = []
    for text, source_url, platform in sources:
        new_sites.extend(_save_text_contacts(
            conn, author_id, text, source_url or "", platform or ""))

    new_sites.extend(r["value"] for r in conn.execute(
        "SELECT value FROM contacts WHERE author_id=? AND kind IN ('website','contact_page')",
        (author_id,)))
    pages_checked = 0
    for website in list(dict.fromkeys(new_sites))[:max(0, max_sites)]:
        pages_checked += _fetch_site_contacts(
            conn, author_id, website, "website", max_site_pages, delay)
    return pages_checked