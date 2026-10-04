#!/usr/bin/env python3
"""Author Outreach — CLI discovery (same engine the dashboard uses).

    python3 run_discovery.py                 # all enabled + built sources
    python3 run_discovery.py --source bluesky
    python3 run_discovery.py --list          # show available platforms
"""
import argparse
import os
import sys

import yaml

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from pipeline import db, report                    # noqa: E402
from pipeline.crawler import CrawlManager          # noqa: E402
from pipeline.sources import REGISTRY              # noqa: E402

BASE = os.path.dirname(os.path.abspath(__file__))


def main():
    ap = argparse.ArgumentParser(description="Author discovery pipeline (CLI)")
    ap.add_argument("--source", choices=[k for k, v in REGISTRY.items() if v["built"]],
                    default=None)
    ap.add_argument("--list", action="store_true")
    args = ap.parse_args()

    if args.list:
        for k, v in REGISTRY.items():
            mark = "✅" if v["built"] else ("⛔" if v["status"] == "blocked" else "⏸")
            print(f"  {mark} {k:15} {v['label']:18} {v['note']}")
        return

    cfg_path = os.path.join(BASE, "config.yaml")
    with open(cfg_path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    if args.source:
        sources = [args.source]
    else:
        sources = [k for k, v in REGISTRY.items()
                   if v["built"] and cfg["sources"].get(k, {}).get("enabled")]

    manager = CrawlManager(cfg_path)
    for s in sources:
        print(f"\n=== {REGISTRY[s]['label']} ===")
        manager.run_sync(s, log=print)

    conn = db.get_conn()
    csv_path, md_path, total = report.export_all(conn, cfg)
    hot = conn.execute("SELECT COUNT(*) c FROM authors WHERE heat_score >= 60").fetchone()["c"]
    pending = conn.execute(
        "SELECT COUNT(*) c FROM suggested_matches WHERE status='pending'").fetchone()["c"]
    conn.close()
    print(f"\n✅ {total} total leads in DB ({hot} hot 🔥, {pending} pending match suggestions)")
    print(f"   CSV:      {csv_path}")
    print(f"   Briefing: {md_path}")
    print(f"   Dashboard: python3 server.py")


if __name__ == "__main__":
    main()
