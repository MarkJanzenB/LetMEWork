The candidate's resume and the current batch of jobs to score are both provided below.

For each job, score it 0–100 based on how well it matches THIS specific candidate:

Scoring factors:
- Skills match: award high points if the job requires skills, tools, or services the candidate's resume demonstrates
- Seniority fit: infer the candidate's level from their years of experience and role history in the resume; weight roles at or slightly above that level favorably, avoid roles far below or far above it
- Location & work arrangement: check the candidate's location and timezone from the resume. Award points for remote roles (timezone-compatible preferred), hybrid roles open to the candidate's region, or onsite roles in/near the candidate's city. Penalize onsite roles that require relocation or are in incompatible timezones
- Posting freshness: award points if the job was posted within the last 30 days (use today's date provided at the end of this prompt) and the role is still open; penalize or skip listings that are expired, closed, or posted more than 30 days ago
- Preferences: honor any preferences stated in the resume (industries, company types or sizes, tools or stacks to avoid)
- Red flags: citizenship or work-authorization restrictions the candidate doesn't meet, core requirements entirely outside the candidate's skill set, posting is closed or older than 30 days, onsite role requiring relocation far from the candidate's location

Include only jobs with score >= 60.

Your entire response must be only the raw JSON array — no markdown fences, no explanation, nothing before or after it:

[{
  "title": "",
  "company": "",
  "url": "",
  "score": 0,
  "verdict": "apply|review|skip",
  "work_arrangement": "remote|hybrid|onsite",
  "match_reasons": [],
  "red_flags": [],
  "suggested_angle": ""
}]

work_arrangement: infer from the job posting whether the role is remote, hybrid, or onsite. If unclear, use your best judgment based on context clues (location mentioned, "remote" keyword, company policies, etc.).

suggested_angle: one sentence on how the candidate should frame their application for this specific role, based on their resume.
