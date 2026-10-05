"""Exports: leads.csv (work the list in any spreadsheet) + leads_report.md
(the daily ranked briefing with suggested angles per author)."""
import csv
import os
from datetime import datetime

from pipeline import db
from pipeline.scoring import GAP_TEXT

HOT, WARM = 60, 40


def _authors(conn, user_id=None):
    sql = (
        """SELECT a.*, COUNT(i.id) AS n_identities,
                  SUM(i.spotted_count) AS total_spots
           FROM authors a LEFT JOIN identities i ON i.author_id = a.id
           {where}
           GROUP BY a.id
           ORDER BY a.heat_score DESC, a.first_seen ASC"""
    )
    where = "WHERE a.user_id=?" if user_id is not None else ""
    args = (user_id,) if user_id is not None else ()
    return conn.execute(sql.format(where=where), args).fetchall()


def _identities(conn, author_id):
    return conn.execute(
        "SELECT * FROM identities WHERE author_id=?", (author_id,)).fetchall()


def _gaps(conn, author_id):
    rows = conn.execute("SELECT gap FROM gaps WHERE author_id=?",
                        (author_id,)).fetchall()
    return [GAP_TEXT.get(r["gap"], r["gap"]) for r in rows]


def _help_posts(conn, max_rows=15, user_id=None):
    """Reddit posts where authors are literally asking for help — warm entry
    points for a helpful reply."""
    keys = ["no sales", "slow sales", "not selling", "struggling",
            "need reviews", "any advice", "how do i", "what am i doing wrong"]
    out = []
    sql = """SELECT p.text, p.post_url, i.handle, i.author_id
             FROM posts p JOIN identities i ON p.identity_id = i.id
             JOIN authors a ON a.id = i.author_id
             WHERE p.platform='reddit'"""
    args = ()
    if user_id is not None:
        sql += " AND a.user_id=?"
        args = (user_id,)
    sql += " ORDER BY p.posted_at DESC"
    for r in conn.execute(sql, args):
        t = (r["text"] or "").lower()
        if any(k in t for k in keys):
            out.append(dict(r))
        if len(out) >= max_rows:
            break
    return out


def export_all(conn, cfg, user_id=None):
    out_dir = os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), cfg["export"]["out_dir"])
    os.makedirs(out_dir, exist_ok=True)
    csv_name = cfg["export"]["csv"]
    md_name = cfg["export"]["report"]
    if user_id is not None:
        csv_base, csv_ext = os.path.splitext(csv_name)
        md_base, md_ext = os.path.splitext(md_name)
        suffix = f"_user_{user_id}"
        csv_name = f"{csv_base}{suffix}{csv_ext}"
        md_name = f"{md_base}{suffix}{md_ext}"
    csv_path = os.path.join(out_dir, csv_name)
    md_path = os.path.join(out_dir, md_name)

    authors = _authors(conn, user_id)

    # ---------- CSV ----------
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["rank", "heat_score", "tier", "platform_handles",
                    "profile_urls", "display_name", "gaps", "suggested_angle",
                    "last_post_days", "posts_per_month", "status", "first_seen",
                    "emails", "email_sources", "websites", "website_sources",
                    "book_titles", "book_urls"])
        for rank, a in enumerate(authors, 1):
            idents = _identities(conn, a["id"])
            handles = " | ".join(f"{i['platform']}:{i['handle']}(x{i['spotted_count']})"
                                 for i in idents)
            urls = " | ".join(i["platform_url"] for i in idents)
            contacts = db.get_contacts(conn, a["id"])
            emails = " | ".join(c["value"] for c in contacts if c["kind"] == "email")
            email_sources = " | ".join(
                f"{c['value']} @ {c['source_url']}" for c in contacts
                if c["kind"] == "email" and c["source_url"])
            websites = " | ".join(c["value"] for c in contacts
                                  if c["kind"] in ("website", "contact_page"))
            website_sources = " | ".join(
                f"{c['value']} @ {c['source_url']}" for c in contacts
                if c["kind"] in ("website", "contact_page") and c["source_url"])
            books = db.get_books(conn, a["id"])
            book_titles = " | ".join(b["title"] for b in books)
            book_urls = " | ".join(b["book_url"] for b in books if b["book_url"])
            tier = "HOT" if a["heat_score"] >= HOT else (
                "WARM" if a["heat_score"] >= WARM else "cool")
            w.writerow([rank, a["heat_score"], tier, handles, urls,
                        a["display_name"], "; ".join(_gaps(conn, a["id"])),
                        a["suggested_angle"], a["last_post_days"],
                        a["posts_per_month"], a["status"], a["first_seen"],
                        emails, email_sources, websites, website_sources,
                        book_titles, book_urls])

    # ---------- Markdown report ----------
    lines = [
        "# 📚 Romantasy Author Leads — Daily Briefing",
        f"*Generated {datetime.utcnow().isoformat(timespec='minutes')}Z*",
        "",
        f"**Total leads:** {len(authors)} · "
        f"🔥 **Hot (≥{HOT}):** {sum(1 for a in authors if a['heat_score'] >= HOT)} · "
        f"🟡 **Warm ({WARM}–{HOT - 1}):** "
        f"{sum(1 for a in authors if WARM <= a['heat_score'] < HOT)}",
        "",
        "---",
        "",
    ]

    hot = [a for a in authors if a["heat_score"] >= HOT]
    if hot:
        lines.append("## 🔥 Hot leads — work these first")
        lines.append("")
        for n, a in enumerate(hot[:20], 1):
            idents = _identities(conn, a["id"])
            plats = " · ".join(
                f"{i['platform']}: `{i['handle']}` (spotted {i['spotted_count']}×)"
                for i in idents)
            contacts = db.get_contacts(conn, a["id"])
            emails = [c["value"] for c in contacts if c["kind"] == "email"]
            websites = [c["value"] for c in contacts
                        if c["kind"] in ("website", "contact_page")]
            books = db.get_books(conn, a["id"])
            bio = next((i["bio"] for i in idents if i["bio"]), "")
            gaps = _gaps(conn, a["id"])
            act = ""
            if a["last_post_days"] is not None:
                act = (f"\n- **Activity:** last posted {a['last_post_days']}d ago · "
                       f"~{a['posts_per_month']} posts/month")
            lines += [
                f"### {n}. {a['display_name'] or 'Unknown'} — score {a['heat_score']}",
                f"- **Where:** {plats}",
                f"- **Profiles:** {' | '.join(i['platform_url'] for i in idents)}",
            ]
            if emails:
                lines.append(f"- **Public email:** {' | '.join(emails)}" + (
                    f" (source: {' | '.join(c['source_url'] for c in contacts if c['kind'] == 'email' and c['source_url'])})"
                    if any(c["kind"] == "email" and c["source_url"] for c in contacts) else ""))
            if websites:
                lines.append(f"- **Author site/contact:** {' | '.join(websites)}" + (
                    f" (source: {' | '.join(c['source_url'] for c in contacts if c['kind'] in ('website', 'contact_page') and c['source_url'])})"
                    if any(c["kind"] in ("website", "contact_page") and c["source_url"] for c in contacts) else ""))
            if books:
                lines.append("- **Books:** " + " | ".join(
                    f"{b['title']} ({b['book_url']})" if b["book_url"] else b["title"]
                    for b in books))
            if bio:
                lines.append(f"- **Bio:** *{bio[:220]}*")
            if gaps:
                lines.append("- **Detected gaps:**")
                lines += [f"  - {g}" for g in gaps]
            lines.append(f"- **Suggested angle:** {a['suggested_angle']}")
            if act:
                lines.append(act.rstrip())
            lines.append("")

    warm = [a for a in authors if WARM <= a["heat_score"] < HOT]
    if warm:
        lines += ["## 🟡 Warm leads", "",
                  "| Score | Author | Platforms | Top gap |",
                  "|---|---|---|---|"]
        for a in warm[:30]:
            idents = _identities(conn, a["id"])
            plats = ", ".join(f"{i['platform']}:{i['handle']}" for i in idents)
            gaps = _gaps(conn, a["id"])
            lines.append(f"| {a['heat_score']} | {a['display_name'] or '?'} | "
                         f"{plats} | {gaps[0] if gaps else '—'} |")
        lines.append("")

    help_posts = _help_posts(conn, user_id=user_id)
    if help_posts:
        lines += ["## 💬 Authors asking for help on Reddit right now — "
                  "reply helpfully, build trust", ""]
        for p in help_posts:
            snippet = (p["text"] or "")[:160].replace("\n", " ")
            lines.append(f"- u/**{p['handle']}**: [{snippet}...]({p['post_url']})")
        lines.append("")

    lines += [
        "---",
        "## How to work this list (etiquette = results)",
        "1. **Reddit:** reply publicly with genuinely useful advice on the "
        "help-seeking posts. Never mass-DM — Reddit bans for it and authors "
        "hate it. Helpful comment → they check your profile → they DM you.",
        "2. **Bluesky:** follow, engage with their posts for a day or two, "
        "then reach out — reference their book and the specific gap you can fix.",
        "3. **Personalize with the gaps:** each message should mention THEIR "
        "book and one concrete gap from this report. That is what the gaps "
        "column is for.",
        "4. Update the `status` column in leads.csv: queued → contacted → "
        "replied → won/lost.",
    ]

    with open(md_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    return csv_path, md_path, len(authors)
