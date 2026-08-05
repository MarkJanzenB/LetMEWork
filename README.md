# Let Me Work

**Local AI job finder for Windows (and local Python).**  
You add your resume and API keys on your PC, run a scrape-and-score pass, then manage matches in a dashboard. Cover letters are on-demand — not auto-written for every job.

**Repo:** [github.com/MarkJanzenB/LetMEWork](https://github.com/MarkJanzenB/LetMEWork)  
**Maintainer:** [Mark Janzen Bandola](https://github.com/MarkJanzenB)  
**Status:** public beta (`0.1.0-beta.x`) — useful, not polished-as-SaaS  
**Changelog:** [`CHANGELOG.md`](CHANGELOG.md) · **Release process:** [`RELEASE.md`](RELEASE.md)

---

## About

**Let Me Work** is a local-first job-hunting assistant: scrape listings, score them against *your* resume with AI, and manage applications from a dashboard on `localhost`. It is the **OpenCode / Windows edition** of [Kurt Chan’s AI Job Hunt Agent](https://github.com/Kurt-Chan/ai-job-scraper) — same host-owned pipeline idea, different AI runtime and product layer.

| | |
|--|--|
| **Who it’s for** | Anyone job hunting (any profession) who wants resume-aware ranking without a SaaS account |
| **What runs where** | App + SQLite + keys on your PC; Firecrawl for fetch; AI via OpenCode → providers you configure |
| **Maintainer** | [Mark Janzen Bandola](https://github.com/MarkJanzenB) |
| **Core workflow credit** | [Kurt Chan](https://github.com/Kurt-Chan) — original scrape → score → dashboard design |
| **License** | MIT ([`LICENSE`](LICENSE), [`NOTICE`](NOTICE)) |

**Roadmap (providers):** keep **running** all scoring through OpenCode; expand **provider-native probing** (Ollama today; Jan / other OpenAI-compatible hubs next) so health checks hit each provider’s API, then sync healthy models into OpenCode before `opencode run`.

---

## What to expect (read this first)

| You get | You do **not** get |
|--------|---------------------|
| A **local** app — keys, resume, and job DB stay on your machine | A cloud account, hosted SaaS, or “set and forget” autopilot apply |
| Scrape + AI score against **your** resume (any profession) | Guaranteed interview offers or perfect match quality |
| Windows **Setup** (unsigned beta) + optional in-app update check | A signed Authenticode installer (SmartScreen may warn) |
| OpenCode as the AI worker (free models when healthy) | Bundled `opencode.exe` inside the installer |
| Firecrawl for search/scrape (you bring the API key) | Unlimited free scraping — Firecrawl quotas are theirs |

**Beta honesty:** models flake, boards change HTML, SmartScreen warns on new publishers, and OpenCode may need a PATH refresh after install. Report issues; don’t expect enterprise SLAs yet.

---

## Provenance (who built what)

Let Me Work is a **derivative work** of [Kurt Chan](https://github.com/Kurt-Chan)’s [AI Job Hunt Agent](https://github.com/Kurt-Chan/ai-job-scraper) (MIT).

### Core workflow — Kurt Chan

The original idea and host-owned pipeline shape:

- Local **FastAPI** host that owns files / API / side effects  
- **Resume → search config → Firecrawl scrape → AI score → dashboard**  
- **Prompts as contracts** (CLI worker returns text; host parses and saves)  
- Claude CLI–era agent loop that this fork rewired to OpenCode  

Support Kurt: [Ko-fi](https://ko-fi.com/kurtdeaustria)

### This edition — Mark Janzen Bandola (Let Me Work)

Product and engineering layers built on that spine:

| Area | What changed |
|------|----------------|
| AI runtime | **OpenCode** instead of Claude CLI; read-only agent; model rotation |
| Reliability | Health **probing** (OpenRouter / Ollama / OpenCode), batch scoring, timeouts, cancel |
| Data | **SQLite** jobs DB, run history, soft-delete / restore, status funnel |
| Product UX | First-run **onboarding** (keys → resume → boards), Settings, confirmations |
| UI | **React + Vite** SPA (FastAPI serves `frontend/dist`); legacy `ui/` fallback |
| Distribution | **PyInstaller + Inno Setup**, OpenCode/Node post-install with retry |
| Updates | Opt-in **auto-update** via GitHub Release `latest.json` (default: notify only) |
| Extras | Firecrawl primary + backup key, AppData BYOK storage, selectable job boards |

Claim line you can use publicly:

> **Let Me Work** is my OpenCode / Windows edition of Kurt Chan’s AI Job Hunt Agent. Kurt designed the core scrape-and-score workflow; I built the OpenCode runtime, SQLite, onboarding, React dashboard, and installer.

MIT license preserved — see [`LICENSE`](LICENSE) and [`NOTICE`](NOTICE).

---

## Privacy (honest)

- **Keys and DB** live under AppData (packaged) or project `data/` / `.env` (dev). No Let Me Work cloud.  
- **Firecrawl** fetches job pages through their API.  
- **Resume text + job text** go to whatever AI providers you configure in OpenCode (often cloud; OpenRouter optional).  
- The installer does **not** ship a third-party `opencode.exe`; it installs OpenCode via official channels when needed.

---

## How it works

```
resume.md (+ keys in AppData/.env or project .env)
   |
   v
1. Profile + search config   AI extracts roles, skills, queries from your resume
   |
   v
2. Discover & scrape         Firecrawl searches boards, scrapes postings
   |
   v
3. Analyze & score           AI scores 0–100, verdict apply / review / skip
   |
   v
4. Cover letters (on demand) Generate per job in the UI when you want
   |
   v
SQLite data/jobs.db (+ optional output/*.json)
```

---

## Stack

- **Python + FastAPI** — pipeline, REST, SSE; serves React in production  
- **[Firecrawl](https://firecrawl.dev)** — search + structured scrape  
- **[OpenCode](https://opencode.ai)** — profile, scoring, cover letters (`prompts/`)  
- **React + Vite + TypeScript** — dashboard (`frontend/`)  
- Free models preferred when healthy; optional OpenRouter; Ollama when local daemon is up  

---

## Models & providers (current)

**Rule:** the pipeline **always runs models through OpenCode** (`opencode run … --model <id>`). Probing may talk to a provider **directly**, then register survivors so OpenCode can see them.

### Ollama (implemented)

1. **Discover** — `GET {OLLAMA_HOST}/api/tags` (default `http://127.0.0.1:11434`; override with env `OLLAMA_HOST`).  
2. **Probe** — each tag via Ollama’s own `POST /api/generate` (not OpenCode).  
3. **Sync into OpenCode** — healthy tags are written to `opencode.json` under `provider.ollama` (OpenAI-compatible `baseURL` `{OLLAMA_HOST}/v1` + a `models` map). See `model_prober.sync_ollama_models_to_opencode`.  
4. **Run** — healthy entries are used as OpenCode ids `ollama/<tag>` during the job pipeline.

Local models and Ollama-served cloud-style tags both work **if** they appear in `/api/tags` and pass the generate probe. If `ollama serve` is down, probing skips Ollama and falls through to other candidates.

### OpenRouter & OpenCode builtins (implemented)

- Optional `OPENROUTER_API_KEY` in `.env` / AppData / Settings.  
- Candidate free models are **probed via** `opencode run` (not OpenRouter’s REST API yet).  
- Built-in OpenCode free models are probed the same way.  
- Results are cached in `data/healthy_models.json` (TTL about one week) and rotated on failure.

### Not first-class yet

**Jan AI**, LM Studio, and other hubs are **not** wired as dedicated probe+sync adapters. You can still use anything OpenCode already supports after `opencode providers login`. Next provider work: same pattern as Ollama — probe the provider natively, sync into `opencode.json`, run only through OpenCode.

---

## Quick start (developers)

Requirements: Python 3.10+, OpenCode on PATH, Firecrawl API key.

```bash
git clone https://github.com/MarkJanzenB/LetMEWork.git
cd LetMEWork
pip install -r requirements.txt
cp .env.example .env          # set FIRECRAWL_API_KEY; OPENROUTER_API_KEY optional

# OpenCode (pick one)
npm install -g opencode-ai
# or: scoop install opencode

opencode providers login      # configure cloud providers as needed

# Optional: Ollama local (or cloud tags exposed by your Ollama)
# ollama serve   # then pull models; Let Me Work probes + syncs into opencode.json

# Resume (gitignored) — or upload via UI after launch
# create resume.md in the project root

python server.py              # http://127.0.0.1:8000
# UI hot-reload (optional): cd frontend && npm install && npm run dev  → :5173
```

Headless once: `python agent.py`  
Tests: `pytest`

Job boards: Settings in the UI, or `config.json`. OnlineJobs.ph is **off by default**.

---

## Windows installer (public beta)

1. Download **LetMeWork-Setup-*.exe** from [Releases](https://github.com/MarkJanzenB/LetMEWork/releases).  
2. If SmartScreen warns: **More info → Run anyway** (unsigned beta — expected).  
3. Finish setup; allow Node/OpenCode install if prompted (retry if it fails).  
4. Complete onboarding: Firecrawl key → resume → at least one board.  
5. Run Agent from the dashboard.

To **cut a new release** (version bump, changelog, tag, installer, GitHub assets): see [`RELEASE.md`](RELEASE.md). In Cursor, ask the agent to “release 0.x.y” and it follows [`.cursor/rules/release.mdc`](.cursor/rules/release.mdc).

Packaging notes: [`packaging/README.md`](packaging/README.md).  
Architecture deep-dive: [`ARCHITECTURE.md`](ARCHITECTURE.md).

---

## Project layout

```
agent.py              # pipeline (OpenCode rotation, streaming)
server.py             # FastAPI + SSE + static React
db.py / user_data.py  # SQLite + AppData keys / onboarding
model_prober.py       # model health cache
frontend/             # React SPA (source + dist)
ui/                   # legacy HTML fallback
prompts/              # AI step prompts
packaging/            # PyInstaller + Inno Setup
```

---

## Credits

| Person | Credit |
|--------|--------|
| **[Kurt Chan](https://github.com/Kurt-Chan)** ([Kurt De Austria](https://ko-fi.com/kurtdeaustria)) | **Core workflow creator** — original [AI Job Hunt Agent](https://github.com/Kurt-Chan/ai-job-scraper): FastAPI host, Firecrawl acquisition, prompt/CLI pipeline, dashboard idea |
| **[Mark Janzen Bandola](https://github.com/MarkJanzenB)** | **Let Me Work maintainer** — OpenCode edition, probing/batching/SSE, SQLite, onboarding, React UI, Windows packaging, update feed |

If this fork helped you, star this repo **and** consider supporting Kurt on [Ko-fi](https://ko-fi.com/kurtdeaustria).

---

## License

MIT — original copyright Kurt De Austria; modifications Copyright © 2026 Mark Janzen Bandola.  
Full text: [`LICENSE`](LICENSE). Attribution summary: [`NOTICE`](NOTICE).
