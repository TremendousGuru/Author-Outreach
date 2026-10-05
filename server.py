#!/usr/bin/env python3
"""Author Outreach — local dashboard server.

Zero extra dependencies (Python stdlib + requests + PyYAML).

    python3 server.py            # http://localhost:8000
    python3 server.py --port 9000
"""
import argparse
import json
import os
import re
import sys
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)

from pipeline import contacts, db, matching, report, scoring # noqa: E402
from pipeline.crawler import CrawlManager, load_config      # noqa: E402
from pipeline.sources import REGISTRY                       # noqa: E402

COOKIE_NAME = "author_outreach_session"

CONFIG_PATH = os.path.join(BASE, "config.yaml")
STATIC_DIR = os.path.join(BASE, "static")
manager = CrawlManager(CONFIG_PATH)

STATUSES = ["new", "reviewing", "messaged", "replied", "won", "lost", "skip"]
TIERS = [("hot", "🔥 Hot (60+)"), ("warm", "🟡 Warm (40–59)"), ("cool", "Cool (<40)")]
CRITERIA = [
    ("reviews_0_50", "Book has 0–50 reviews"),
    ("just_launched", "Just launched / debut"),
    ("low_popularity", "Not yet popular"),
    ("weak_ad_content", "Weak advertising content"),
]


def check_links(book, author_name):
    t = urllib.parse.quote(f"{book['title']} {author_name or ''}".strip())
    return {
        "amazon": f"https://www.amazon.com/s?k={t}",
        "goodreads": f"https://www.goodreads.com/search?q={t}",
    }


def get_current_user(req):
    token = None
    if req.headers.get("Authorization", "").startswith("Bearer "):
        token = req.headers.get("Authorization").split(" ", 1)[1].strip()
    if not token:
        token = req.headers.get("Cookie", "").split(COOKIE_NAME + "=", 1)[1].split(";", 1)[0] if COOKIE_NAME + "=" in req.headers.get("Cookie", "") else None
    if not token:
        return None
    conn = db.get_conn()
    try:
        return db.get_session_user(conn, token)
    finally:
        conn.close()


def require_user(req):
    user = get_current_user(req)
    if not user:
        raise PermissionError("login required")
    if user["status"] != "approved":
        raise PermissionError("account is pending approval")
    return user


def leads_payload(conn, qs, user_id=None):
    platform = qs.get("platform", [""])[0]
    tier = qs.get("tier", [""])[0]
    status = qs.get("status", [""])[0]
    criterion = qs.get("criterion", [""])[0]
    contact = qs.get("contact", [""])[0]
    q = qs.get("q", [""])[0].lower().strip()
    try:
        page = max(1, int(qs.get("page", ["1"])[0]))
    except ValueError:
        page = 1
    per = 25

    sql = "SELECT a.* FROM authors a WHERE 1=1"
    args = []
    if user_id is not None:
        sql += " AND a.user_id=?"
        args.append(user_id)
    if platform:
        sql += " AND EXISTS (SELECT 1 FROM identities i WHERE i.author_id=a.id AND i.platform=?)"
        args.append(platform)
    if tier == "hot":
        sql += " AND a.heat_score >= 60"
    elif tier == "warm":
        sql += " AND a.heat_score BETWEEN 40 AND 59"
    elif tier == "cool":
        sql += " AND a.heat_score < 40"
    if status:
        sql += " AND a.status = ?"
        args.append(status)
    if contact == "email":
        sql += " AND EXISTS (SELECT 1 FROM contacts c WHERE c.author_id=a.id AND c.kind='email')"
    elif contact == "website":
        sql += """ AND EXISTS (SELECT 1 FROM contacts c WHERE c.author_id=a.id
                  AND c.kind IN ('website','contact_page'))"""
    if q:
        sql += """ AND (LOWER(a.display_name) LIKE ?
             OR EXISTS (SELECT 1 FROM identities i2 WHERE i2.author_id=a.id
                        AND LOWER(i2.handle) LIKE ?))"""
        args += [f"%{q}%", f"%{q}%"]
    sql += " ORDER BY a.heat_score DESC, a.last_seen DESC LIMIT 1500"
    rows = conn.execute(sql, args).fetchall()

    ids = [r["id"] for r in rows]
    plats, books_n, gap_keys, books_map, contact_kinds = {}, {}, {}, {}, {}
    if ids:
        chunk = ",".join("?" * len(ids))
        for r in conn.execute(
                f"SELECT author_id, platform FROM identities WHERE author_id IN ({chunk}) AND (user_id IS NULL OR user_id=?)", [*ids, user_id] if user_id is not None else ids):
            plats.setdefault(r["author_id"], []).append(r["platform"])
        for r in conn.execute(
                f"SELECT author_id, COUNT(*) c FROM books WHERE author_id IN ({chunk}) AND (user_id IS NULL OR user_id=?) GROUP BY author_id", [*ids, user_id] if user_id is not None else ids):
            books_n[r["author_id"]] = r["c"]
        for r in conn.execute(
                f"SELECT author_id, gap FROM gaps WHERE author_id IN ({chunk}) AND (user_id IS NULL OR user_id=?)", [*ids, user_id] if user_id is not None else ids):
            gap_keys.setdefault(r["author_id"], []).append(r["gap"])
        for r in conn.execute(
                f"SELECT * FROM books WHERE author_id IN ({chunk}) AND (user_id IS NULL OR user_id=?)", [*ids, user_id] if user_id is not None else ids):
            books_map.setdefault(r["author_id"], []).append(r)
        for r in conn.execute(
                f"SELECT author_id, kind FROM contacts WHERE author_id IN ({chunk}) AND (user_id IS NULL OR user_id=?)", [*ids, user_id] if user_id is not None else ids):
            contact_kinds.setdefault(r["author_id"], set()).add(r["kind"])

    annotated = []
    for r in rows:
        crit = scoring.evaluate_criteria(
            books_map.get(r["id"], []), {"gaps": gap_keys.get(r["id"], [])})
        annotated.append({
            "id": r["id"], "display_name": r["display_name"],
            "heat_score": r["heat_score"], "status": r["status"],
            "platforms": sorted(set(plats.get(r["id"], []))),
            "books": books_n.get(r["id"], 0),
            "has_email": "email" in contact_kinds.get(r["id"], set()),
            "has_website": bool({"website", "contact_page"} &
                                contact_kinds.get(r["id"], set())),
            "gaps": gap_keys.get(r["id"], []),
            "criteria": crit, "last_seen": r["last_seen"],
        })
    if criterion:
        annotated = [a for a in annotated if a["criteria"].get(criterion) is True]

    total = len(annotated)
    pages = max(1, -(-total // per))
    page = min(page, pages)
    return {"rows": annotated[(page - 1) * per: page * per],
            "total": total, "page": page, "pages": pages}


def author_payload(conn, aid, user_id=None):
    if user_id is not None:
        a = conn.execute("SELECT * FROM authors WHERE id=? AND user_id=?", (aid, user_id)).fetchone()
    else:
        a = conn.execute("SELECT * FROM authors WHERE id=?", (aid,)).fetchone()
    if not a:
        return None
    idents = [dict(r) for r in conn.execute(
        "SELECT * FROM identities WHERE author_id=? ORDER BY first_seen", (aid,))]
    if user_id is not None:
        idents = [i for i in idents if i.get('user_id') in (None, user_id)]
    books = [dict(r) for r in db.get_books(conn, aid)]
    if user_id is not None:
        books = [b for b in books if b.get('user_id') in (None, user_id)]
    contact_rows = [dict(r) for r in db.get_contacts(conn, aid)]
    if user_id is not None:
        contact_rows = [c for c in contact_rows if c.get('user_id') in (None, user_id)]
    posts = db.get_posts(conn, aid)[:30]
    gap_rows = conn.execute(
        "SELECT gap FROM gaps WHERE author_id=?", (aid,)).fetchall()
    gap_keys = [g["gap"] for g in gap_rows]

    cfg = load_config(CONFIG_PATH)
    analysis = scoring.analyze(db.get_author_text(conn, aid), posts, cfg)
    criteria = scoring.evaluate_criteria(books, {"gaps": gap_keys})
    for b in books:
        b["check"] = check_links(b, a["display_name"])
        b["gap_texts"] = [scoring.GAP_TEXT.get(g, g) for g in gap_keys]
    return {
        "id": a["id"], "display_name": a["display_name"],
        "heat_score": a["heat_score"], "status": a["status"],
        "notes": a["notes"] or "", "first_seen": a["first_seen"],
        "last_seen": a["last_seen"], "last_post_days": a["last_post_days"],
        "posts_per_month": a["posts_per_month"],
        "suggested_angle": a["suggested_angle"],
        "identities": idents, "books": books, "posts": posts,
        "contacts": contact_rows,
        "gaps": [scoring.GAP_TEXT.get(g, g) for g in gap_keys],
        "gap_keys": gap_keys, "criteria": criteria,
        "signals": analysis["signals"],
    }


class Handler(BaseHTTPRequestHandler):
    server_version = "AuthorOutreach/1.0"

    def log_message(self, fmt, *args):
        pass

    # ---------- plumbing ----------
    def _json(self, obj, code=200):
        body = json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _file(self, path, ctype):
        try:
            with open(path, "rb") as f:
                body = f.read()
        except OSError:
            self._json({"error": "not found"}, 404)
            return
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _body(self):
        try:
            n = int(self.headers.get("Content-Length", 0))
        except ValueError:
            n = 0
        if not n:
            return {}
        try:
            return json.loads(self.rfile.read(n).decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return {}

    # ---------- routes ----------
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path, qs = parsed.path, urllib.parse.parse_qs(parsed.query)
        try:
            if path == "/api/auth/me":
                conn = db.get_conn()
                try:
                    user = get_current_user(self)
                    if not user or user["status"] != "approved":
                        self._json({"user": None}, 401)
                    else:
                        self._json({"user": {"id": user["id"], "username": user["username"], "role": user["role"], "status": user["status"]}})
                finally:
                    conn.close()
                return
            if path in ("/login", "/signup", "/admin"):
                self._file(os.path.join(STATIC_DIR, "index.html"), "text/html; charset=utf-8")
                return
            if path in ("/", "/index.html"):
                self._file(os.path.join(STATIC_DIR, "index.html"),
                           "text/html; charset=utf-8")
            elif path == "/api/platforms":
                cfg = load_config(CONFIG_PATH)
                out = []
                for key, meta in REGISTRY.items():
                    out.append({
                        "key": key, "label": meta["label"],
                        "group": meta["group"], "status": meta["status"],
                        "built": meta["built"], "note": meta["note"],
                        "enabled": cfg["sources"].get(key, {}).get("enabled", False),
                    })
                conn = db.get_conn()
                try:
                    counts = {r["platform"]: r["c"] for r in conn.execute(
                        "SELECT platform, COUNT(*) c FROM identities GROUP BY platform")}
                    pending = conn.execute(
                        "SELECT COUNT(*) c FROM suggested_matches WHERE status='pending'").fetchone()["c"]
                    total = conn.execute("SELECT COUNT(*) c FROM authors").fetchone()["c"]
                    self._json({"platforms": out, "identity_counts": counts,
                                "pending_matches": pending, "total_authors": total})
                finally:
                    conn.close()
            elif path == "/api/crawl/status":
                self._json(manager.status())
            elif path == "/api/leads":
                conn = db.get_conn()
                try:
                    user = require_user(self)
                    self._json(leads_payload(conn, qs, user_id=user["id"]))
                except PermissionError:
                    self._json({"error": "login required"}, 401)
                finally:
                    conn.close()
            elif path == "/api/author/count":
                conn = db.get_conn()
                try:
                    user = require_user(self)
                    self._json({"total": conn.execute(
                        "SELECT COUNT(*) c FROM authors WHERE user_id=?", (user["id"],)).fetchone()["c"]})
                except PermissionError:
                    self._json({"error": "login required"}, 401)
                finally:
                    conn.close()
            elif path.startswith("/api/matches"):
                conn = db.get_conn()
                try:
                    user = require_user(self)
                    self._json({"matches": matching.pending(conn)})
                except PermissionError:
                    self._json({"error": "login required"}, 401)
                finally:
                    conn.close()
            else:
                m = re.match(r"^/api/author/(\d+)$", path)
                if m:
                    conn = db.get_conn()
                    try:
                        user = require_user(self)
                        p = author_payload(conn, int(m.group(1)), user_id=user["id"])
                        self._json(p if p else {"error": "not found"}, 200 if p else 404)
                    except PermissionError:
                        self._json({"error": "login required"}, 401)
                    finally:
                        conn.close()
                else:
                    self._json({"error": "not found"}, 404)
        except Exception as e:  # noqa: BLE001
            self._json({"error": str(e)}, 500)

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        body = self._body()
        try:
            if path == "/api/auth/login":
                username = str(body.get("username") or "").strip()
                password = str(body.get("password") or "")
                if not username or not password:
                    self._json({"ok": False, "error": "username and password required"}, 400)
                    return
                conn = db.get_conn()
                try:
                    user = db.get_user_by_login(conn, username)
                    if not user or user["status"] != "approved":
                        self._json({"ok": False, "error": "account not approved or not found"}, 401)
                        return
                    if not db.verify_password(conn, user["id"], password):
                        self._json({"ok": False, "error": "invalid password"}, 401)
                        return
                    token = db.create_session(conn, user["id"])
                    self.send_response(200)
                    self.send_header("Set-Cookie", f"{COOKIE_NAME}={token}; Path=/; HttpOnly; SameSite=Lax")
                    self.send_header("Content-Type", "application/json; charset=utf-8")
                    self.end_headers()
                    self.wfile.write(json.dumps({"ok": True, "user": {"id": user["id"], "username": user["username"], "role": user["role"], "status": user["status"]}}).encode("utf-8"))
                finally:
                    conn.close()
                return
            if path == "/api/auth/logout":
                conn = db.get_conn()
                try:
                    token = None
                    cookie = self.headers.get("Cookie", "")
                    if COOKIE_NAME + "=" in cookie:
                        token = cookie.split(COOKIE_NAME + "=", 1)[1].split(";", 1)[0]
                    if token:
                        db.end_session(conn, token)
                    self.send_response(200)
                    self.send_header("Set-Cookie", f"{COOKIE_NAME}=; Path=/; HttpOnly; SameSite=Lax; Max-Age=0")
                    self.send_header("Content-Type", "application/json; charset=utf-8")
                    self.end_headers()
                    self.wfile.write(json.dumps({"ok": True}).encode("utf-8"))
                finally:
                    conn.close()
                return
            if path == "/api/auth/signup":
                username = str(body.get("username") or "").strip()
                email = str(body.get("email") or "").strip().lower()
                password = str(body.get("password") or "")
                full_name = str(body.get("full_name") or "").strip()
                if not username or not password:
                    self._json({"ok": False, "error": "username and password required"}, 400)
                    return
                conn = db.get_conn()
                try:
                    user = db.create_user(conn, email=email or f"{username}@authoroutreach.local", password=password, username=username, full_name=full_name, role="user", status="pending")
                    self._json({"ok": True, "message": "account created and awaiting admin approval", "user": {"id": user["id"], "status": user["status"]}})
                except ValueError as e:
                    self._json({"ok": False, "error": str(e)}, 409)
                finally:
                    conn.close()
                return
            if path == "/api/admin/users":
                conn = db.get_conn()
                try:
                    user = require_user(self)
                    if user["role"] != "admin":
                        raise PermissionError("admin only")
                    users = [dict(r) for r in db.list_users(conn)]
                    self._json({"ok": True, "users": users})
                except PermissionError:
                    self._json({"error": "admin login required"}, 401)
                finally:
                    conn.close()
                return
            if path == "/api/admin/approve":
                conn = db.get_conn()
                try:
                    user = require_user(self)
                    if user["role"] != "admin":
                        raise PermissionError("admin only")
                    target_id = int(body.get("user_id"))
                    action = body.get("action", "approve")
                    if action == "approve":
                        db.approve_user(conn, target_id, approved_by=user["username"])
                    else:
                        conn.execute("UPDATE users SET status='rejected', approved_by=?, approved_at=?, updated_at=? WHERE id=?", (user["username"], db.now_iso(), db.now_iso(), target_id))
                    conn.commit()
                    self._json({"ok": True})
                except PermissionError:
                    self._json({"error": "admin login required"}, 401)
                finally:
                    conn.close()
                return
            enrich_match = re.match(r"^/api/author/(\d+)/enrich$", path)
            if enrich_match:
                conn = db.get_conn()
                try:
                    user = require_user(self)
                    author_id = int(enrich_match.group(1))
                    if not conn.execute("SELECT 1 FROM authors WHERE id=? AND user_id=?", (author_id, user["id"])).fetchone():
                        self._json({"error": "not found"}, 404)
                        return
                    before = len(db.get_contacts(conn, author_id))
                    cfg = load_config(CONFIG_PATH).get("contact_enrichment", {})
                    checked = contacts.enrich_author(
                        conn, author_id,
                        max_site_pages=max(1, int(cfg.get("max_pages_per_site", 4))),
                        max_sites=max(0, int(cfg.get("max_sites_per_author", 2))),
                        delay=max(0, float(cfg.get("delay_seconds", 0.8))))
                    conn.commit()
                    total = len(db.get_contacts(conn, author_id))
                    self._json({"ok": True, "checked": checked,
                                "added": max(0, total - before), "total": total})
                except PermissionError:
                    self._json({"error": "login required"}, 401)
                finally:
                    conn.close()
            elif path == "/api/crawl":
                platform = body.get("platform")
                ok, msg = manager.start(platform)
                self._json({"ok": ok, "message": msg}, 200 if ok else 409)
            elif path == "/api/matches/scan":
                conn = db.get_conn()
                try:
                    user = require_user(self)
                    n = matching.scan(conn)
                    self._json({"added": n})
                except PermissionError:
                    self._json({"error": "login required"}, 401)
                finally:
                    conn.close()
            elif path == "/api/export":
                conn = db.get_conn()
                try:
                    user = require_user(self)
                    cfg = load_config(CONFIG_PATH)
                    csv_path, md_path, total = report.export_all(
                        conn, cfg, user_id=user["id"])
                    self._json({"csv": csv_path, "md": md_path, "total": total})
                except PermissionError:
                    self._json({"error": "login required"}, 401)
                finally:
                    conn.close()
            else:
                m = re.match(r"^/api/matches/(\d+)/(confirm|reject)$", path)
                if not m:
                    self._json({"error": "not found"}, 404)
                    return
                conn = db.get_conn()
                try:
                    user = require_user(self)
                    if m.group(2) == "confirm":
                        kept = matching.confirm(conn, int(m.group(1)))
                        if kept:
                            crawler_cfg = load_config(CONFIG_PATH)
                            analysis = scoring.analyze(
                                db.get_author_text(conn, kept),
                                db.get_posts(conn, kept), crawler_cfg)
                            db.save_analysis(conn, kept, analysis)
                            conn.commit()
                        self._json({"ok": kept is not None, "kept": kept})
                    else:
                        matching.reject(conn, int(m.group(1)))
                        self._json({"ok": True})
                except PermissionError:
                    self._json({"error": "login required"}, 401)
                finally:
                    conn.close()
        except Exception as e:  # noqa: BLE001
            self._json({"error": str(e)}, 500)

    def do_PATCH(self):
        m = re.match(r"^/api/author/(\d+)$", urllib.parse.urlparse(self.path).path)
        if not m:
            self._json({"error": "not found"}, 404)
            return
        body = self._body()
        conn = db.get_conn()
        try:
            aid = int(m.group(1))
            if "status" in body or "notes" in body:
                db.set_author_fields(conn, aid, status=body.get("status"),
                                     notes=body.get("notes"))
                conn.commit()
            book = body.get("book")
            if book and book.get("id"):
                db.update_book_manual(conn, book["id"],
                                      book.get("amazon_reviews"),
                                      book.get("goodreads_ratings"))
                conn.commit()
            self._json({"ok": True})
        except Exception as e:  # noqa: BLE001
            self._json({"error": str(e)}, 500)
        finally:
            conn.close()


def main():
    ap = argparse.ArgumentParser(description="Author Outreach dashboard")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--host", default="0.0.0.0")
    args = ap.parse_args()
    os.makedirs(os.path.join(BASE, "data"), exist_ok=True)
    print(f"\n  📚 Author Outreach dashboard")
    print(f"  ➜ http://localhost:{args.port}\n")
    httpd = ThreadingHTTPServer((args.host, args.port), Handler)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n  stopped")


if __name__ == "__main__":
    main()
