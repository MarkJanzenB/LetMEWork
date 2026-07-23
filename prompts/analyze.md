The candidate's structured profile, raw resume, and the current batch of jobs to score are all provided below. Use the structured profile as the primary reference for scoring — it has pre-extracted experience, skills, education, projects, and preferences.

For each job, score it 0–100 based on how well it matches THIS specific candidate:

Scoring factors:
- Skills match: compare the job's requirements against the candidate's structured skills (programming, frameworks, ai_ml, backend_data, embedded, tools). Award high points when the job requires skills the candidate has demonstrated in work or projects — not just listed. Cross-reference projects to find real-world application of skills.
- Experience fit: use experience_years and the roles array to judge seniority. Weight roles at or slightly above the candidate's level favorably. Penalize roles requiring far more or far less experience than the candidate has.
- Education: check if the job requires a specific degree. The candidate has a BS in Information Technology. Penalize only if the job strictly requires a different field (e.g., "BS in Mechanical Engineering required").
- Location & work arrangement: use the candidate's location, timezone, and preferred work_arrangement from the profile. Award points for remote roles (timezone-compatible preferred), hybrid roles open to the candidate's region, or onsite roles in/near the candidate's city. Penalize onsite roles that require relocation or are in incompatible timezones.
- Project relevance: if the job's domain or tech stack overlaps with the candidate's projects, award bonus points. The candidate's projects demonstrate real-world AI/automation and full-stack development.
- Posting freshness: award points if the job was posted within the last 30 days (use today's date provided at the end of this prompt) and the role is still open; penalize or skip listings that are expired, closed, or posted more than 30 days ago.
- Preferences: honor any preferences stated in the profile (industries, company types or sizes, tools or stacks to avoid).
- Red flags: citizenship or work-authorization restrictions the candidate doesn't meet, core requirements entirely outside the candidate's skill set, posting is closed or older than 30 days, onsite role requiring relocation far from the candidate's location.

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

suggested_angle: one sentence on how the candidate should frame their application for this specific role. Reference specific projects or experience from the profile that directly relate to the job's requirements.