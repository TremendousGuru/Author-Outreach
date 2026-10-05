"""Streamlit Community Cloud entrypoint for Author Outreach."""
import os
import sys
from pathlib import Path

import streamlit as st

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))

from pipeline import contacts, db, matching, report, scoring  # noqa: E402
from pipeline.crawler import CrawlManager, load_config  # noqa: E402
from pipeline.sources import REGISTRY  # noqa: E402

CONFIG_PATH = BASE / "config.yaml"

st.set_page_config(page_title="Author Outreach", page_icon="📚", layout="wide")
st.title("Author Outreach")
st.caption("Public-data author discovery and outreach research")


def configure_admin_secret():
    try:
        admin = st.secrets.get("admin", {})
    except Exception:
        admin = {}
    if admin.get("password"):
        os.environ["AUTHOR_OUTREACH_ADMIN_PASSWORD"] = str(admin["password"])
        os.environ["AUTHOR_OUTREACH_ADMIN_USERNAME"] = str(admin.get("username", "Tremendous"))
        os.environ["AUTHOR_OUTREACH_ADMIN_EMAIL"] = str(admin.get("email", "admin@authoroutreach.local"))


def get_manager():
    return CrawlManager(str(CONFIG_PATH))


@st.cache_resource
def shared_manager():
    return get_manager()


def open_db():
    configure_admin_secret()
    return db.get_conn()


def login_view():
    st.subheader("Sign in")
    login_tab, signup_tab = st.tabs(["Login", "Request access"])
    with login_tab:
        with st.form("login-form"):
            login = st.text_input("Username or email")
            password = st.text_input("Password", type="password")
            submitted = st.form_submit_button("Login", type="primary")
        if submitted:
            conn = open_db()
            try:
                user = db.get_user_by_login(conn, login)
                if not user or user["status"] != "approved":
                    st.error("Account not found or awaiting admin approval.")
                elif not db.verify_password(conn, user["id"], password):
                    st.error("Invalid username or password.")
                else:
                    st.session_state.user = {
                        "id": user["id"], "username": user["username"],
                        "role": user["role"], "status": user["status"],
                    }
                    st.rerun()
            finally:
                conn.close()
    with signup_tab:
        with st.form("signup-form"):
            username = st.text_input("Username")
            email = st.text_input("Email")
            new_password = st.text_input("Password", type="password")
            submitted = st.form_submit_button("Create account")
        if submitted:
            if not username.strip() or not email.strip() or len(new_password) < 12:
                st.error("Enter a username, email, and password of at least 12 characters.")
            else:
                conn = open_db()
                try:
                    db.create_user(conn, email, new_password, username=username,
                                   full_name=username, role="user", status="pending")
                    st.success("Account created. An administrator must approve it before login.")
                except ValueError as exc:
                    st.error(str(exc))
                finally:
                    conn.close()
    st.info("Set the initial administrator in Streamlit Cloud under App settings → Secrets. See README for the required format.")


def admin_users(conn):
    st.subheader("Account approvals")
    users = db.list_users(conn)
    pending = [user for user in users if user["status"] == "pending"]
    if not pending:
        st.info("No accounts are awaiting approval.")
        return
    for user in pending:
        left, right = st.columns([4, 1])
        left.write(f"**{user['username']}** · {user['email']}")
        if right.button("Approve", key=f"approve-{user['id']}"):
            db.approve_user(conn, user["id"], approved_by=st.session_state.user["username"])
            st.rerun()


def crawl_page(conn, user):
    st.subheader("Crawl public sources")
    if user["role"] != "admin":
        st.warning("Crawling is currently restricted to the administrator because crawl records are shared by the existing pipeline.")
        return
    manager = shared_manager()
    config = load_config(str(CONFIG_PATH))
    available = [key for key, meta in REGISTRY.items()
                 if meta["built"] and config["sources"].get(key, {}).get("enabled", False)]
    platform = st.selectbox("Platform", available,
                            format_func=lambda key: REGISTRY[key]["label"])
    if st.button("Start crawl", type="primary", disabled=manager.status()["running"]):
        ok, message = manager.start(platform)
        (st.success if ok else st.error)(message)
    if st.button("Refresh crawl status"):
        st.rerun()
    status = manager.status()
    st.write("Status:", "Running" if status["running"] else "Idle")
    if status["stats"]:
        st.write(status["stats"])
    if status["log"]:
        st.code("\n".join(status["log"][-30:]))
    st.caption("Cloud instances may stop background crawls when they sleep or restart.")


def leads_page(conn, user):
    st.subheader("Leads")
    if user["role"] == "admin":
        identities = conn.execute(
            "SELECT DISTINCT platform FROM identities ORDER BY platform").fetchall()
    else:
        identities = conn.execute(
            "SELECT DISTINCT platform FROM identities WHERE user_id=? ORDER BY platform",
            (user["id"],)).fetchall()
    platforms = ["Any"] + [row["platform"] for row in identities]
    search_col, platform_col, status_col = st.columns([2, 1, 1])
    search = search_col.text_input("Search author")
    platform = platform_col.selectbox("Platform", platforms)
    status = status_col.selectbox("Status", ["Any", "new", "reviewing", "messaged", "replied", "won", "lost", "skip"])
    authors = db.get_leads(
        conn, user_id=user["id"], search=search, platform=platform,
        status=status, include_all=user["role"] == "admin")
    if not authors:
        st.info("No leads for this account yet.")
        return
    st.caption(f"{len(authors)} leads shown. No score threshold is applied.")
    rows = [{"Score": author["heat_score"], "Author": author["display_name"],
             "Status": author["status"], "Last seen": author["last_seen"]}
            for author in authors]
    st.caption("Select a table row to open that author's profile.")
    selection = st.dataframe(
        rows, use_container_width=True, hide_index=True,
        on_select="rerun", selection_mode="single-row",
        key=f"leads-{user['id']}-{platform}-{status}-{search}")
    if selection.selection.rows:
        selected_index = selection.selection.rows[0]
        author_profile(conn, authors[selected_index]["id"], user["id"],
                       is_admin=user["role"] == "admin")


def author_profile(conn, author_id, user_id, is_admin=False):
    if is_admin:
        author = conn.execute("SELECT * FROM authors WHERE id=?", (author_id,)).fetchone()
    else:
        author = conn.execute("SELECT * FROM authors WHERE id=? AND user_id=?",
                              (author_id, user_id)).fetchone()
    if not author:
        st.error("Author not found.")
        return
    st.markdown(f"### {author['display_name'] or 'Unknown author'} · {author['heat_score']}/100")
    identities = conn.execute("SELECT * FROM identities WHERE author_id=?", (author_id,)).fetchall()
    books = db.get_books(conn, author_id)
    contact_rows = db.get_contacts(conn, author_id)
    config = load_config(str(CONFIG_PATH))
    analysis = scoring.analyze(
        db.get_author_text(conn, author_id), db.get_posts(conn, author_id), config)
    qualifying_books = scoring.books_meeting_criteria(books, analysis)
    left, right = st.columns(2)
    with left:
        st.markdown("**Profiles**")
        for identity in identities:
            st.markdown(f"- [{identity['platform']}: {identity['handle']}]({identity['platform_url']})")
        st.markdown("**Books meeting criteria**")
        if qualifying_books:
            for item in qualifying_books:
                book = item["book"]
                st.markdown(f"**{book['title']}**")
                st.caption("Meets: " + ", ".join(item["criteria"]))
                if book["book_url"]:
                    st.markdown(f"[Open source listing]({book['book_url']})")
        else:
            st.info("No books currently meet a known criterion. Add review counts or publication dates when available.")
        st.markdown("**Books**")
        for book in books:
            st.markdown(f"- [{book['title']}]({book['book_url']})" if book["book_url"] else f"- {book['title']}")
    with right:
        st.markdown("**Public contacts**")
        for contact in contact_rows:
            st.write(f"{contact['kind']}: {contact['value']}")
    with st.form(f"author-{author_id}"):
        status = st.selectbox("Outreach status", ["new", "reviewing", "messaged", "replied", "won", "lost", "skip"], index=["new", "reviewing", "messaged", "replied", "won", "lost", "skip"].index(author["status"]))
        notes = st.text_area("Private notes", value=author["notes"] or "")
        if st.form_submit_button("Save changes"):
            db.set_author_fields(conn, author_id, status=status, notes=notes)
            conn.commit()
            st.success("Saved.")


def matches_page(conn, user):
    st.subheader("Suggested matches")
    if user["role"] != "admin":
        st.info("Match review is currently administrator-only because the matching pipeline is shared.")
        return
    if st.button("Scan for matches"):
        st.success(f"Added {matching.scan(conn)} suggestions.")
    matches = matching.pending(conn)
    for item in matches:
        with st.container(border=True):
            st.write(f"**{item['name_a']}** ↔ **{item['name_b']}**")
            st.caption(item["reason"])
            confirm_col, reject_col = st.columns(2)
            if confirm_col.button("Confirm merge", key=f"confirm-{item['id']}"):
                matching.confirm(conn, item["id"])
                st.rerun()
            if reject_col.button("Reject", key=f"reject-{item['id']}"):
                matching.reject(conn, item["id"])
                st.rerun()
    if not matches:
        st.info("No pending matches.")


def export_page(conn, user):
    st.subheader("Export your leads")
    config = load_config(str(CONFIG_PATH))
    user_id = None if user["role"] == "admin" else user["id"]
    csv_path, report_path, total = report.export_all(conn, config, user_id=user_id)
    st.write(f"Prepared exports for {total} leads.")
    csv_bytes = Path(csv_path).read_bytes()
    report_bytes = Path(report_path).read_bytes()
    col_csv, col_report = st.columns(2)
    col_csv.download_button("Download CSV", csv_bytes, file_name="leads.csv", mime="text/csv")
    col_report.download_button("Download report", report_bytes, file_name="leads_report.md", mime="text/markdown")


def main():
    configure_admin_secret()
    if "user" not in st.session_state:
        st.session_state.user = None
    if not st.session_state.user:
        login_view()
        return
    user = st.session_state.user
    with st.sidebar:
        st.write(f"Signed in as **{user['username']}**")
        if st.button("Log out"):
            st.session_state.user = None
            st.rerun()
        page = st.radio("Workspace", ["Crawl", "Leads", "Matches", "Export"])
        if user["role"] == "admin":
            page += ""
    conn = open_db()
    try:
        if user["role"] == "admin":
            admin_users(conn)
        if page == "Crawl":
            crawl_page(conn, user)
        elif page == "Leads":
            leads_page(conn, user)
        elif page == "Matches":
            matches_page(conn, user)
        else:
            export_page(conn, user)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
