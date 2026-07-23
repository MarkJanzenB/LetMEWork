The candidate's resume is provided below. Extract a structured profile for use by downstream prompts.

Output ONLY a valid JSON object — no markdown fences, no explanation, no extra text — in this exact shape:

{
  "name": "",
  "location": "",
  "timezone": "",
  "work_arrangement": "remote|hybrid|onsite|flexible",
  "experience_years": 0,
  "experience_summary": "",
  "roles": [],
  "education": [],
  "skills": {
    "programming": [],
    "frameworks": [],
    "ai_ml": [],
    "backend_data": [],
    "embedded": [],
    "tools": [],
    "soft_skills": []
  },
  "projects": [],
  "preferences": "",
  "portfolio_url": ""
}

Rules:
- name: full name from the resume header
- location: city, country from the resume
- timezone: infer from location (e.g. "GMT+8" for Philippines)
- work_arrangement: the candidate's preferred arrangement based on resume context; use "flexible" if open to any
- experience_years: total years of professional experience (full-time + part-time combined, count from earliest to latest role)
- experience_summary: one sentence summarizing career level and primary domain
- roles: array of strings, each a concise role title + company + duration (e.g. "AI Systems Developer at Lifewood (Jan 2026 – May 2026)")
- education: array of objects with "degree", "institution", "year", "location"
- skills: grouped by category. Extract from both the skills section AND work experience. Include only skills the candidate has demonstrated (not just listed)
- projects: array of objects with "name", "one_liner", "stack" (array of technologies), and "url" if available
- preferences: any stated preferences about industry, company size, tools to avoid, etc. Empty string if none stated
- portfolio_url: the candidate's portfolio or personal website URL if present

Your entire response must be only the raw JSON object — nothing before or after it.