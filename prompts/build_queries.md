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
- search_queries: Firecrawl-ready search strings combining role titles and skills with site: prefixes. Use OR operators for breadth. Produce exactly one query per job board listed at the end of this prompt, plus exactly one grouped query per Reddit subreddit group listed there. Use the candidate's location and timezone from the profile to include location-aware keywords: "remote" for remote roles, and the candidate's city/country for onsite or hybrid roles. Every query must target work arrangements compatible with the candidate's location.

Reddit query format — combine the subreddits of one group with OR, and include the group's extra terms if it has any:
  "(site:reddit.com/r/jobbit OR site:reddit.com/r/remotejobs OR site:reddit.com/r/WorkOnline) (React OR Next.js OR \"Full Stack\") TypeScript"

Example job board query formats:
  "site:wellfound.com (Next.js OR React) TypeScript remote developer"
  "site:onlinejobs.ph (\"Virtual Assistant\" OR \"Executive Assistant\") \"calendar management\""
  "site:linkedin.com/jobs (Python OR \"AI Developer\") \"Cebu\" OR \"Philippines\" OR remote"

Your entire response must be only the raw JSON object — nothing before or after it. The job boards and Reddit groups to cover follow below.