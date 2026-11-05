# Development instructions

- Follow docs/PRD.md and the staged acceptance plan in docs/ACCEPTANCE.md.
- This checkout is already isolated; use it directly. Do not create worktrees unless requested.
- Current scope: stage seven reproducible evaluation, authorized dataset contracts, ranking/claim metrics, independent feedback and honest eight-demo evidence. Preserve all prior ACLs; never report synthetic tests as real customer/model quality.
- Public catalog mutations require the separate operator-granted is_data_curator capability; organization administrators cannot publish shared facts by default.
- Keep imported unknown values unknown; never merge companies automatically on name similarity. Keep provenance and soft-deleted/merged originals.
- Python 3.12+, Node.js 22+; TypeScript strict mode. Keep lockfiles committed.
- API: `cd services/api && uv sync --frozen --extra dev`; run commands with `uv run`.
- Web: `cd apps/web && npm ci`; validate with `npm test`, `npm run typecheck`, `npm run build`.
- Run `uv run pytest ../../tests/unit` from services/api. Integration tests require Compose dependencies; see README.
- Never commit .env, credentials, raw client documents or generated files.
- All external services use environment settings; all provider calls must go through app.agents.gateway.
- Private resources must eventually enforce organization AND project permissions in backend code, with adversarial tests before release.
- Keep fact, inference, unverified, unknown and conflicting distinct; do not invent financial or company data.
- Public health endpoints expose only dependency status, not connection strings, exceptions or secrets.
- Use Alembic for schema changes; no automatic create_all on application startup.
