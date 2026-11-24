# أسعارك — Asarak

Egypt's independent price tracking, fake-discount detection, and cross-store price comparison platform across **200 Egyptian retailers** and **112,000+ tracked products** in EGP.

- **Live Web App:** <https://asarak.com> (Cloudflare Workers via `@opennextjs/cloudflare`)
- **Live API:** <https://api.asarak.com> (FastAPI on Railway + Neon PostgreSQL)
- **Contact:** `contact@asarak.com`

## Repository Structure

- `web_app/frontend/` — Next.js 15 (App Router, Arabic RTL / English LTR) deployed to Cloudflare Workers (`asarak-web`).
- `web_app/backend/` — FastAPI serving layer + price-drop alert jobs deployed to Railway.
- `data_platform/` — Multi-store Egyptian scrapers, cross-store canonical matcher, and dbt transformations (`raw` → `silver` → `gold` in Neon PostgreSQL).
- `scripts/` — Local residential scraper runner (`run_local_scrapers.ps1`) and scheduler helpers.
