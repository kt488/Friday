# OpenClaude Wiki Schema

This wiki stores durable, human-readable project knowledge for Friday.

## Goals

- Keep useful project knowledge in markdown, not only in chat history
- Prefer synthesized facts over raw copy-paste
- Keep source attribution explicit
- Make pages easy for both humans and agents to update

## Structure

- `index.md`: top-level navigation and major topics
- `log.md`: append-only update log
- `pages/`: durable topic and architecture pages
- `sources/`: source ingestion notes and summaries

## Page Rules

- Keep pages focused on one topic
- Use stable headings such as:
  - `## Summary`
  - `## Key Facts`
  - `## Relationships`
  - `## Open Questions`
  - `## Sources`
- Add or update facts only when they are grounded in project files or explicit source notes
- Prefer editing an existing page over creating duplicates
