# AI Job Hunt Agent — OpenCode Edition

[![Support me on Ko-fi](https://img.shields.io/badge/Ko--fi-Support%20this%20project-FF5E5B?logo=ko-fi&logoColor=white)](https://ko-fi.com/kurtdeaustria)

An autonomous job-hunting pipeline. It reads your resume, searches the web for matching roles (remote, hybrid, and onsite), scores each posting against your actual profile with an AI agent, and drafts a tailored cover letter for every job worth applying to — all reviewable in a local web dashboard.

It works for **any profession** — developer, designer, virtual assistant, writer, accountant, marketer. Everything (target roles, search queries, scoring, cover letters) is derived from your `resume.md`; nothing about your field is hardcoded.

## Based on

This project is built on the work of **[Kurt Chan](https://github.com/Kurt-Chan)** — the original creator of [AI Job Hunt Agent](https://github.com/Kurt-Chan/ai-job-scraper). The original project used the Claude CLI as its AI layer and provided the core pipeline architecture (resume parsing, Firecrawl scraping, job scoring, cover letter generation, and the FastAPI dashboard). Without that foundation, this version would not exist.

This fork extends the original with:

- **OpenCode as the AI engine** — replaces Claude CLI with OpenCode, using free models only to keep costs at zero
- **Dynamic model health probing** — discovers and tests models across OpenRouter, Ollama (Gemma 4 cloud), and OpenCode built-in providers, caching results to `data/healthy_models.json`
- **Batched job analysis** — splits large job sets into batches of 30 so free models can handle them without stalling
- **Live streaming output** — real-time logs with heartbeats and dual stall detection (hard timeout + silence timeout)
- **Inlined prompt context** — resume and job data are injected directly into prompts so models don't need file-read tools
- **Mecha/spaceship UI redesign** — custom design system with Fraunces, Space Grotesk, and JetBrains Mono; neon lime accents, LED badges, and pill CTAs
- **Work arrangement indicators** — Remote / Hybrid / Onsite badges on each job card
- **Score range toggle** — cycles between All / 80+ / 60-79, filtering both display and bulk-apply
- **Bulk apply with tab opening** — marks matching jobs as applied and opens their URLs
- **Copy-to-clipboard** on cover letter modal
- **SQLite database layer** — full pipeline run history in `data/jobs.db`

All original credits and the MIT license apply. Please also support the original creator:

[![ko-fi](https://img.shields.io/badge/Kurt_Chan-Ko--fi-FF5E5B?logo=ko-fi&logoColor=white)](https://ko-fi.com/kurtdeaustria)

## How it works

```
resume.md
   |
   v
1. Build search config   AI extracts target roles, key skills, and
   |                     search queries from your resume
   v
2. Discover & scrape     Firecrawl runs the queries, then scrapes each
   |                     result page and extracts individual postings
   v
3. Analyze & score       AI scores every posting 0-100 against your
   |                     profile (skills, seniority, work arrangement,
   |                     freshness, red flags) and gives a verdict
   v
4. Cover letters         For each "apply" verdict, AI drafts a short
   |                     cover letter using a suggested angle per job
   v
output/jobs.json + output/cover_letters/*.md
```

A FastAPI server (`server.py`) exposes the pipeline and results, and `ui/index.html` is a single-file dashboard with live progress (Server-Sent Events), score/verdict filtering, status tracking, and a cover-letter viewer.

All data is stored in a SQLite database (`data/jobs.db`) with full history tracking. The previous JSON files are still supported for backward compatibility.

## Stack

- **Python + FastAPI** — pipeline orchestration and API
- **[Firecrawl](https://firecrawl.dev)** — web search and structured scraping (LLM extraction with a JSON schema)
- **[OpenCode](https://opencode.ai)** — open-source AI agent used as the AI layer for resume analysis, job scoring, and cover-letter writing via prompt files in `prompts/`
- **Vanilla JS** — zero-build single-file UI
- **FREE MODELS ONLY** — Rotates through free models across OpenRouter, Ollama, and OpenCode to avoid charges

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

**Important:** This project is configured to use ONLY free models. Never change to paid models without understanding the cost implications. Model health is probed and cached automatically at `data/healthy_models.json`.

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
python server.py            # -> http://127.0.0.1:8000

# Or headless
python agent.py
```

Results are stored in the SQLite database (`data/jobs.db`) with full history. The `output/` directory still contains JSON files for backward compatibility.

## How the AI integration works

The pipeline uses OpenCode's `run` command in non-interactive mode. A custom agent (`job-agent`) is defined in `opencode.json` with **read-only permissions** — it can read your resume and scraped jobs but cannot write files, which forces it to output text that the pipeline parses.

```
opencode run "<prompt>" --agent job-agent --model <free-model>
```

**Model Health Probing:** On first run, the system probes all available models across OpenRouter, Ollama, and OpenCode providers. Healthy models are cached to `data/healthy_models.json` (1-hour TTL). The pipeline rotates through healthy models indefinitely, retrying 3 times per model before skipping.

**Batched Analysis:** Job scoring is split into batches of 30 jobs per model call to keep context small enough for free models. Each batch is analyzed separately and results are merged.

**Live Streaming:** Output is streamed line-by-line with 30-second heartbeats, dual stall detection (10-minute hard cap + 90-second silence timeout), and partial output logging on failure.

## Tests

```bash
pytest
```

## Project structure

```
agent.py              # 4-step pipeline with model rotation and streaming
config.py             # centralized configuration (thresholds, timeouts, models)
config.json           # search sources: job boards + Reddit subreddit groups
model_prober.py       # model health probing across providers
db.py                 # SQLite database layer
server.py             # FastAPI: /api/jobs, /api/status, /api/cover-letter, /api/run (SSE)
ui/index.html         # single-file mecha dashboard
prompts/              # prompt files for each AI step (data inlined)
opencode.json         # OpenCode config: agent definitions
CLAUDE.md             # agent context (loaded by OpenCode automatically)
resume.md             # your resume (gitignored)
test_pipeline.py      # pipeline unit tests
test_server.py        # API tests
data/jobs.db          # SQLite database (auto-created)
data/healthy_models.json  # cached healthy models (auto-probed)
```

## Credits

- **[Kurt Chan](https://github.com/Kurt-Chan)** — Original creator of [AI Job Hunt Agent](https://github.com/Kurt-Chan/ai-job-scraper). Core pipeline architecture, FastAPI server, Firecrawl integration, and the original Claude CLI workflow.
- **Mark Janzen Bandola** — OpenCode integration, dynamic model health probing, batched analysis, live streaming output, mecha UI redesign, work arrangement indicators, and the free-models-only architecture.

## Support

Built while job hunting as a broke developer — it runs on OpenCode (free models included) and Firecrawl's free tier precisely because I couldn't justify another bill. **This project uses ONLY free models to keep costs at zero.** If it helped you land interviews (or saved you a few hours of job-board scrolling), consider buying me a coffee:

[![ko-fi](https://ko-fi.com/img/githubbutton_sm.svg)](https://ko-fi.com/kurtdeaustria)

Stars, issues, and PRs are just as appreciated.
