"""Crawl orchestrator: runs one platform adapter at a time in a background
thread, streams progress lines to the dashboard, re-analyzes touched authors,
then scans for cross-platform matches. Used by both the web dashboard
(server.py) and the CLI (run_discovery.py).
"""
import threading
from collections import deque

import yaml

from pipeline import contacts, db, matching, scoring
from pipeline.sources import REGISTRY, get_adapter

BASE = ""  # filled by server/cli


def load_config(path):
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


class CrawlManager:
    def __init__(self, config_path):
        self.config_path = config_path
        self.lock = threading.Lock()
        self.thread = None
        self.running = False
        self.platform = None
        self.log = deque(maxlen=400)
        self.stats = {}

    # ---- helpers ----
    def emit(self, kind, payload):
        if kind == "log":
            self.log.append(str(payload))
        elif kind == "author":
            aid, is_new = payload
            s = self.stats
            s["touched"] = s.get("touched", 0) + 1
            if is_new:
                s["new"] = s.get("new", 0) + 1
            else:
                s["updated"] = s.get("updated", 0) + 1

    def status(self):
        with self.lock:
            return {
                "running": self.running,
                "platform": self.platform,
                "log": list(self.log)[-60:],
                "stats": dict(self.stats),
            }

    # ---- execution ----
    def _run(self, platform):
        cfg = load_config(self.config_path)
        conn = db.get_conn()
        cur = conn.execute(
            "INSERT INTO crawl_runs(platform, started_at, status) VALUES (?,?,?)",
            (platform, db.now_iso(), "running"))
        run_id = cur.lastrowid
        conn.commit()
        try:
            adapter = get_adapter(platform)
            stats = adapter.crawl(cfg, self.emit, conn)
            touched = stats.get("touched", []) if isinstance(stats, dict) else []
            self.emit("log", f"Re-analyzing {len(set(touched))} authors (gaps, score, angle)…")
            contact_cfg = cfg.get("contact_enrichment", {})
            site_limit = max(0, int(contact_cfg.get("max_authors_per_crawl", 12)))
            site_pages = max(1, int(contact_cfg.get("max_pages_per_site", 4)))
            site_count = max(0, int(contact_cfg.get("max_sites_per_author", 2)))
            site_delay = max(0, float(contact_cfg.get("delay_seconds", 0.8)))
            site_slots_used = 0
            for author_id in sorted(set(touched)):
                scan_site = site_slots_used < site_limit
                contacts.enrich_author(
                    conn, author_id,
                    max_site_pages=site_pages if scan_site else 0,
                    max_sites=site_count, delay=site_delay)
                if scan_site:
                    site_slots_used += 1
                analysis = scoring.analyze(
                    db.get_author_text(conn, author_id),
                    db.get_posts(conn, author_id), cfg)
                db.save_analysis(conn, author_id, analysis)
            conn.commit()
            self.emit("log", f"Public contact enrichment complete; site checks enabled for {site_slots_used} author(s).")
            n = matching.scan(conn)
            if n:
                self.emit("log", f"Cross-reference: {n} new suggested match(es) queued for review.")
            conn.execute(
                "UPDATE crawl_runs SET finished_at=?, new_authors=?, updated_authors=?, status='done' WHERE id=?",
                (db.now_iso(), self.stats.get("new", 0), self.stats.get("updated", 0), run_id))
            conn.commit()
            self.emit("log", "✅ Crawl complete.")
        except Exception as e:
            self.emit("log", f"❌ Crawl failed: {e}")
            try:
                conn.execute("UPDATE crawl_runs SET finished_at=?, status='failed', note=? WHERE id=?",
                             (db.now_iso(), str(e)[:300], run_id))
                conn.commit()
            except Exception:
                pass
        finally:
            conn.close()
            with self.lock:
                self.running = False

    def start(self, platform):
        with self.lock:
            if self.running:
                return False, "a crawl is already running"
            if platform not in REGISTRY or not REGISTRY[platform].get("built"):
                return False, "platform not available"
            if not load_config(self.config_path)["sources"].get(platform, {}).get("enabled", True):
                pass  # allow manual one-off run even if disabled by default
            self.running = True
            self.platform = platform
            self.log.clear()
            self.stats = {}
        self.emit("log", f"▶ Starting crawl: {REGISTRY[platform]['label']}…")
        self.thread = threading.Thread(target=self._run, args=(platform,), daemon=True)
        self.thread.start()
        return True, "started"

    def run_sync(self, platform, log=print):
        """CLI mode: run in the current thread."""
        with self.lock:
            if self.running:
                return False, "a crawl is already running"
            self.running = True
            self.platform = platform
            self.log.clear()
            self.stats = {}
        self.emit("log", f"▶ Starting crawl: {REGISTRY[platform]['label']}…")
        try:
            self._run(platform)
        finally:
            with self.lock:
                self.running = False
        for line in list(self.log)[-8:]:
            log(line)
        return True, "done"


def reanalyze_author(conn, author_id, cfg):
    analysis = scoring.analyze(db.get_author_text(conn, author_id),
                               db.get_posts(conn, author_id), cfg)
    db.save_analysis(conn, author_id, analysis)
    conn.commit()
    return analysis
