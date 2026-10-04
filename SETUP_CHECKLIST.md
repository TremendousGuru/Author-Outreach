# Author Outreach System — Setup Checklist & Requirements

**Project:** Author prospecting + personalized outreach pipeline
**Goal:** Discover 100+ authors/day across platforms → enrich their profiles → detect marketing gaps → send tailored outreach (email-first) → track replies and per-source attribution.

---

## 1. System Architecture (agreed)

```
[Stage 1] DISCOVERY          [Stage 2] ENRICHMENT      [Stage 3] BOOK DATA     [Stage 4] GAP DETECTION    [Stage 5] OUTREACH
─────────────────────        ────────────────────      ─────────────────       ────────────────────      ──────────────────
Platform adapters:           Username cross-check      Amazon listing:         Auto-scored signals:      Cold email engine
 • Bluesky (free API)         Author website scan        rank, reviews,         • reviews vs rank         50–100/day per inbox
 • Reddit (free API)          Email extraction           price, categories      • email capture?          Warm-up schedule
 • Mastodon (free)            Social profile links       pub date, A+ content   • website quality         Suppression list
 • Threads (paid API)         Genre identification       (Keepa later)          • posting vs sales        Per-source reply
 • (NO Facebook scraping)                                                      • 1-book stagnation         attribution
                                                                               → auto-draft email
                                                                                 (LLM) w/ 3–5 gaps
```

**Core design rule (your idea):** each platform is a separate adapter, configured and enabled independently. Every prospect is tagged per-platform (`identities[]` with `spotted_count`, `last_seen`). Cross-platform dedup merges the same author into one record — "found on N platforms" = heat signal.

---

## 2. What We Need — Checklist

### Phase 1 — MVP (FREE, start immediately)
- [ ] **Bluesky account** → settings → Privacy & Security → App Passwords → create one. Give me: handle + app password.
- [ ] **Reddit app credentials** → reddit.com/prefs/apps → create "script" app → give me: client ID + client secret. (5 minutes)
- [ ] **Your niche decision** (see Questions below)
- [ ] **Your offer + rough pricing** (what the outreach email sells)
- [ ] **Sender name + email signature** you'll use
- [ ] **Physical/business address line** for email footer (CAN-SPAM)
- [ ] **Your social handles** (Bluesky/Threads) for warm-up engagement

### Phase 2 — Volume engine (small budget)
- [ ] **Outreach domain** — ~$10–15/yr (NOT your main brand domain; protects reputation). Ask me for naming advice.
- [ ] **1–2 sending inboxes** on that domain — Zoho Mail (~$1/user/mo) or Google Workspace (~$6/user/mo)
- [ ] **LLM API key** for auto-drafted personalized emails — Gemini free tier / Groq free tier, or OpenAI (~$5–20/mo)
- [ ] Warm-up: 2–3 weeks of gradual sending before hitting 50–100/day

### Phase 3 — Scale (optional, once revenue flows)
- [ ] **Threads data API** — EnsembleData / SocialCrawl / Apify (free trial credits, then ~$30–80/mo)
- [ ] **Keepa API** — Amazon rank & review history (~€49/mo) — replaces lighter Amazon checks
- [ ] **Email verification** — ZeroBounce/NeverBounce free tier (protects deliverability)
- [ ] **Instantly or Smartlead** (~$30–37/mo) — managed inbox rotation, warmup, and sending (alternative to self-managed)
- [ ] **VPS** (~$5/mo) or GitHub Actions cron — runs the pipeline daily without your machine on

---

## 3. Prospect Qualification Criteria (defaults — confirm or edit)

| # | Criterion | Default |
|---|-----------|---------|
| 1 | Published book exists (ebook or print) | Required |
| 2 | Language / market | English, selling into US/UK |
| 3 | Platform activity | Posted in last 30 days |
| 4 | Exclusions | Aspiring/unpublished writers, celebrity trad authors, publishers, agents, book marketers |
| 5 | Heat score inputs | Few reviews + active posting + no email capture + weak/absent website = HOT |

---

## 4. Compliance Guardrails (built into the system)

- Public data only; no logged-in scraping of Facebook/Instagram/Threads
- Email: real identity, honest subject lines, working unsubscribe, physical address in footer
- Per-inbox daily caps + human-like delays + warm-up schedule
- Suppression list (opt-outs never contacted again)
- EU/UK prospects: business-relevant data only, legitimate-interest basis, easy opt-out
- Never buy email lists

---

## 5. Open Questions (blocking build start)

1. **Niche:** romantasy/series-fiction authors, or business/nonfiction author-experts, or both?
2. **Budget tier:** free-only to start, or ~$25–50/mo, or ~$100+/mo?
3. **Do you already own a domain/website** for your brand (for sender identity + portfolio link)?
4. **First MVP source:** Bluesky, Reddit, or both free ones together?

---

*Last updated: 2026-10-02*
