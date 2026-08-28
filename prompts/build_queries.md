The candidate's structured profile and raw resume are provided below. Use the structured profile for efficient lookup; refer to the raw resume only for details not in the profile.

Output ONLY a valid JSON object — no markdown fences, no explanation, no extra text — in this exact shape:

{
  "target_roles": [],
  "key_skills": [],
  "search_queries": []
}

Rules:
- target_roles: 4–6 job title variants based on the candidate's actual experience. Prioritize roles that match the candidate's demonstrated skills and seniority level (from experience_years and roles).
- key_skills: the top 6–8 skills the candidate is strongest in — use the structured profile's skills grouped by category. Prioritize skills that appear in BOTH the skills section and work experience.
- search_queries: Firecrawl-ready search strings. Produce exactly one query per job board listed at the end of this prompt. Each query MUST include a matching `site:` prefix for that board only (e.g. `site:indeed.com`, `site:jobstreet.com`, `site:linkedin.com/jobs`). Never invent boards that are not listed.
- Location (strict): use the candidate's city/country from the profile. Prefer local keywords (city + country). Do NOT add other countries. Do NOT write queries that primarily target foreign cities (US, UK, India, EU, etc.).
- Work arrangement (strict): only use keywords compatible with the Allowed work arrangements list at the end of this prompt.
  - If `remote` is allowed: you may include remote / WFH terms, still paired with the candidate's country when useful (e.g. `"Philippines" remote`).
  - If `remote` is NOT allowed: do not add unconstrained global "remote" OR clauses.
  - If only `onsite` / `hybrid`: bias queries toward the candidate's city/country and those arrangement words.

Example formats (adapt to the listed boards + arrangements):
  "site:jobstreet.com (\"Full Stack\" OR Python) Philippines OR Cebu"
  "site:onlinejobs.ph (\"Virtual Assistant\" OR \"Executive Assistant\") Philippines"
  "site:linkedin.com/jobs (Python OR \"AI Developer\") \"Philippines\" remote"

Your entire response must be only the raw JSON object — nothing before or after it. The job boards and allowed work arrangements follow below.
