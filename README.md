# Let Me Work — OpenCode Edition

[![Support me on Ko-fi](https://img.shields.io/badge/Ko--fi-Support%20this%20project-FF5E5B?logo=ko-fi&logoColor=white)](https://ko-fi.com/kurtdeaustria)

**Let Me Work** is a local-first AI job finder. You run it on your PC, add your resume and API keys, then trigger a scrape-and-score run from the dashboard. Cover letters are on-demand (per job), not auto-written for every match.

It works for **any profession** — developer, designer, virtual assistant, writer, accountant, marketer. Target roles, search queries, scoring, and cover letters are derived from your `resume.md`; nothing about your field is hardcoded.

### Privacy (honest)

- Keys and the job DB stay on your machine (AppData when packaged; project `data/` in dev). There is no Let Me Work cloud account.
- Job pages are fetched via **Firecrawl** (their API).
- Resume text and job content are sent to the **AI providers you configure** through OpenCode (often cloud models; OpenRouter optional).
- OpenCode is **not** bundled in the Windows installer — install it yourself (PATH or post-install).

## Based on

Built on **[Kurt Chan](https://github.com/Kurt-Chan)**’s [AI Job Hunt Agent](https://github.com/Kurt-Chan/ai-job-scraper) (Claude CLI + Firecrawl + FastAPI dashboard). This fork swaps in OpenCode, model health probing, SQLite, and the Let Me Work UI/packaging.

This fork extends the original with:

- **OpenCode as the AI engine** — replaces Claude CLI; prefers free models when available
- **Dynamic model health probing** — OpenRouter, Ollama, OpenCode providers → `data/healthy_models.json`
- **Batched job analysis** — batches of 30 for smaller free-model contexts
- **Live streaming output** — SSE logs, heartbeats, stall detection
- **Inlined prompt context** — resume/jobs injected so models need fewer file tools
- **Mecha UI** — single-file dashboard (`ui/index.html`)
- **Work arrangement + score filters**, bulk apply, on-demand cover letters
- **SQLite** — `data/jobs.db` with run history

All original credits and the MIT license apply. Please also support the original creator:

[![ko-fi](https://img.shields.io/badge/Kurt_Chan-Ko--fi-FF5E5B?logo=ko-fi&logoColor=white)](https://ko-fi.com/kurtdeaustria)

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
3. Analyze & score           AI scores 0–100, verdict apply/review/skip
   |
   v
4. Cover letters (on demand) You generate per job in the UI when you want
   |
   v
SQLite data/jobs.db (+ optional output/*.json under config.OUTPUT_DIR)
```

Run the dashboard (`python server.py` → http://127.0.0.1:8000) or headless (`python agent.py`). First launch walks you through keys + resume.

## Stack

- **Python + FastAPI** — pipeline and API
- **[Firecrawl](https://firecrawl.dev)** — search and structured scrape
- **[OpenCode](https://opencode.ai)** — AI for profile, scoring, cover letters (`prompts/`)
- **Vanilla JS** — zero-build UI
- Free models preferred when healthy; optional OpenRouter key for more models

## Setup

Requirements: Python 3.10+, [OpenCode](https://opencode.ai) on PATH, Firecrawl API key.

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

Configure a provider (free models when possible):

```bash
opencode providers login
```

Optional: set `OPENROUTER_API_KEY` for OpenRouter models. Model health is probed and cached at `data/healthy_models.json`.

See the [OpenCode docs](https://opencode.ai/docs/providers/) for providers.

### 3. Set up environment

```bash
cp .env.example .env        # FIRECRAWL_API_KEY required; OPENROUTER_API_KEY optional
```

Packaged builds store keys under your user AppData folder (shown in the onboarding wizard).

### 4. Add your resume

Create `resume.md` in the project root (markdown — gitignored), or upload a text PDF in the UI. The file stays on your disk; its **text** is sent to whatever AI provider OpenCode uses when you run the agent.

### 5. Optional: customize search sources

Edit `config.json` for `job_boards`. OnlineJobs.ph is available in Settings but **off by default** (account verification often blocks applying). Defaults cover major boards — add field-specific boards if you need them.

## Run

```bash
# Web dashboard
python server.py            # -> http://127.0.0.1:8000

# Or headless
python agent.py
```

Results live in SQLite (`data/jobs.db`). JSON under `output/` is still written for convenience.

## How the AI integration works

The pipeline uses OpenCode's `run` command in non-interactive mode. A custom agent (`job-agent`) is defined in `opencode.json` with **read-only permissions** — it can read your resume and scraped jobs but cannot write files, which forces it to output text that the pipeline parses.

```
opencode run "<prompt>" --agent job-agent --model <model>
```

**Model health:** On first need, models are probed across providers; healthy ones are cached. The pipeline rotates through them with a hard attempt ceiling (`MAX_OPENCODE_ATTEMPTS`).

**Batched analysis:** Scoring uses batches of ≤30 jobs per call.

**Live streaming:** Line-by-line SSE with heartbeats and stall detection (hard cap + silence timeout).

## Tests

```bash
pytest
```

## Project structure

```
agent.py              # pipeline with model rotation and streaming
config.py             # thresholds, timeouts, OUTPUT_DIR
config.json           # job boards
model_prober.py       # model health probing
db.py                 # SQLite
server.py             # FastAPI + SSE
ui/index.html         # dashboard
prompts/              # AI step prompts
opencode.json         # OpenCode agent definitions
user_data.py          # AppData paths, keys, onboarding
CLAUDE.md / AGENTS.md # agent context
resume.md             # your resume (gitignored)
test_pipeline.py
test_server.py
data/jobs.db
data/healthy_models.json
```

## Credits

- **[Kurt Chan](https://github.com/Kurt-Chan)** — Original [AI Job Hunt Agent](https://github.com/Kurt-Chan/ai-job-scraper). Core pipeline, FastAPI, Firecrawl, Claude CLI workflow.
- **Mark Janzen Bandola** — OpenCode edition, probing, batching, streaming, Let Me Work UI/packaging.

## Support

Built to run on free-tier Firecrawl and free OpenCode models when available. If it helped, consider supporting Kurt:

[![ko-fi](https://ko-fi.com/img/githubbutton_sm.svg)](https://ko-fi.com/kurtdeaustria)

Stars, issues, and PRs are appreciated.
