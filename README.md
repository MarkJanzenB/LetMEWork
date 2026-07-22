# AI Job Hunt Agent

[![Support me on Ko-fi](https://img.shields.io/badge/Ko--fi-Support%20this%20project-FF5E5B?logo=ko-fi&logoColor=white)](https://ko-fi.com/kurtdeaustria)

An autonomous job-hunting pipeline. It reads your resume, searches the web for matching remote roles, scores each posting against your actual profile with an AI agent, and drafts a tailored cover letter for every job worth applying to — all reviewable in a local web dashboard.

It works for **any profession** — developer, designer, virtual assistant, writer, accountant, marketer. Everything (target roles, search queries, scoring, cover letters) is derived from your `resume.md`; nothing about your field is hardcoded.

## How it works

```
resume.md
   │
   ▼
1. Build search config   AI extracts target roles, key skills, and
   │                     search queries from your resume
   ▼
2. Discover & scrape     Firecrawl runs the queries, then scrapes each
   │                     result page and extracts individual postings
   ▼
3. Analyze & score       AI scores every posting 0–100 against your
   │                     profile (stack match, seniority, remote signals,
   │                     freshness, red flags) and gives a verdict
   ▼
4. Cover letters         For each "apply" verdict, AI drafts a short
   │                     cover letter using a suggested angle per job
   ▼
output/jobs.json + output/cover_letters/*.md
```

A FastAPI server (`server.py`) exposes the pipeline and results, and `ui/index.html` is a single-file dashboard with live progress (Server-Sent Events), score/verdict filtering, status tracking (none → applied → ignored → interviewed → rejected → hired), and a cover-letter viewer.

All data is stored in a SQLite database (`data/jobs.db`) with full history tracking. The previous JSON files are still supported for backward compatibility.

## Stack

- **Python + FastAPI** — pipeline orchestration and API
- **[Firecrawl](https://firecrawl.dev)** — web search and structured scraping (LLM extraction with a JSON schema)
- **[OpenCode](https://opencode.ai)** — open-source AI coding agent used as the AI layer for resume analysis, job scoring, and cover-letter writing via prompt files in `prompts/`
- **Vanilla JS** — zero-build single-file UI
- **FREE MODELS ONLY** — Rotates through free OpenRouter/Zen models to avoid charges

## Setup

Requirements: Python 3.10+, [OpenCode](https://opencode.ai) installed and configured with a provider, and a Firecrawl API key.

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Install and configure OpenCode

```bash
# Install opencode (pick one method)
curl -fsSL https://opencode.ai/install | bash    # macOS/Linux
npm install -g opencode-ai                        # cross-platform
scoop install opencode                            # Windows
```

Then configure an AI provider. This project uses **FREE models only** to avoid charges:

```bash
# Option A: Use OpenCode Zen free models (recommended)
opencode providers login

# Option B: Use OpenRouter free models (requires API key, but models are free)
opencode providers login
```

**⚠️ IMPORTANT:** This project is configured to use ONLY free models. Never change to paid models without understanding the cost implications.

See the [OpenCode docs](https://opencode.ai/docs/providers/) for all supported providers.

### 3. Set up environment

```bash
cp .env.example .env        # add your FIRECRAWL_API_KEY
```

### 4. Add your resume

Create `resume.md` in the project root (markdown format — it is gitignored and never leaves your machine). See the existing `resume.md` for an example.

### 5. Optional: customize search sources

Edit `config.json` to change where the agent searches: `job_boards` is the list of sites to query (one search each), and `reddit_groups` are groups of subreddits (one grouped search each, with optional `extra_terms` added to the query). The defaults cover LinkedIn, Indeed, Wellfound, Glassdoor, JobStreet, OnlineJobs.ph, and a set of profession-neutral hiring subreddits — if your field has dedicated boards or subreddits (e.g. Dribbble for designers, r/VirtualAssistant for VAs), add them here.

## Run

```bash
# Web dashboard
python server.py            # → http://127.0.0.1:8000

# Or headless
python agent.py

# Migrate existing JSON data to database (one-time)
python migrate_json_to_db.py
```

Results are stored in the SQLite database (`data/jobs.db`) with full history. The `output/` directory still contains JSON files for backward compatibility.

## How the AI integration works

The pipeline uses OpenCode's `run` command in non-interactive mode. A custom agent (`job-agent`) is defined in `opencode.json` with **read-only permissions** — it can read your resume and scraped jobs but cannot write files, which forces it to output text that the pipeline parses.

```
opencode run "<prompt>" --agent job-agent --model <free-model>
```

**Free Model Rotation:** The pipeline rotates through free models (nemotron-3-super, gemma-4, gpt-oss, etc.) to avoid rate limits and charges. Never use paid models.

The agent picks up `CLAUDE.md` automatically (OpenCode supports Claude Code's file conventions) for system-level instructions.

## Tests

```bash
pytest
```

## Project structure

```
agent.py              # 4-step pipeline (search config → scrape → analyze → cover letters)
config.json           # search sources: job boards + Reddit subreddit groups
opencode.json         # OpenCode config: agent definition with read-only permissions
CLAUDE.md             # agent context (loaded by OpenCode automatically)
.opencode/agents/     # OpenCode agent definitions
  job-agent.md        # read-only job hunting agent
server.py             # FastAPI: /api/jobs, /api/status, /api/cover-letter, /api/run (SSE)
ui/index.html         # single-file dashboard
prompts/              # prompt files for each AI step
resume.md             # your resume (gitignored — add your own)
test_pipeline.py      # pipeline unit tests (AI/Firecrawl mocked)
test_server.py        # API tests
db.py                 # SQLite database layer (schema, CRUD, migration helpers)
data/jobs.db          # SQLite database (auto-created on first run)
migrate_json_to_db.py # One-time migration from JSON files to database
```

## Support

I built this while job hunting as a broke developer — it runs on OpenCode (free models included) and Firecrawl's free tier precisely because I couldn't justify another bill. **This project uses ONLY free models to keep costs at zero.** If it helped you land interviews (or saved you a few hours of job-board scrolling), consider buying me a coffee:

[![ko-fi](https://ko-fi.com/img/githubbutton_sm.svg)](https://ko-fi.com/kurtdeaustria)

Stars, issues, and PRs are just as appreciated.
