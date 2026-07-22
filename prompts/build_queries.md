The candidate's resume is provided below. The candidate can be in any profession — developer, designer, virtual assistant, writer, accountant, marketer, etc. Derive everything from what the resume actually says.

Output ONLY a valid JSON object — no markdown fences, no explanation, no extra text — in this exact shape:

{
  "target_roles": [],
  "key_skills": [],
  "search_queries": []
}

Rules:
- target_roles: 4–6 job title variants based on the candidate's actual experience. Examples: a developer resume might yield "Frontend Developer" and "React Developer"; a virtual assistant resume might yield "Virtual Assistant", "Executive Assistant", and "Administrative Assistant".
- key_skills: the top 6–8 skills, tools, or services the candidate is strongest in, extracted from their skills section and work experience (prioritize what appears in both).
- search_queries: Firecrawl-ready search strings combining role titles and skills with site: prefixes. Use OR operators for breadth. Produce exactly one query per job board listed at the end of this prompt, plus exactly one grouped query per Reddit subreddit group listed there. Read the candidate's location from the resume and include location-aware keywords: include "remote" to find remote roles, but also include the candidate's city/country or "nearby" when targeting onsite or hybrid roles. Every query must target work arrangements compatible with the candidate's location.

Reddit query format — combine the subreddits of one group with OR, and include the group's extra terms if it has any:
  "(site:reddit.com/r/jobbit OR site:reddit.com/r/remotejobs OR site:reddit.com/r/WorkOnline) (React OR Next.js OR \"Full Stack\") TypeScript"

Example job board query formats:
  "site:wellfound.com (Next.js OR React) TypeScript remote developer"
  "site:onlinejobs.ph (\"Virtual Assistant\" OR \"Executive Assistant\") \"calendar management\""
  "site:linkedin.com/jobs (Python OR \"AI Developer\") \"Cebu\" OR \"Philippines\" OR remote"

Your entire response must be only the raw JSON object — nothing before or after it. The job boards and Reddit groups to cover follow below.
