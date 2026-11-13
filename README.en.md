# meet’cool ✳

[Try the bilingual preview](https://meetcool-hk5r71d6v-ac-07b0.vercel.app/?lang=en)

[Français](README.md) · [Technical report for the teacher (French)](docs/POUR_LE_PROF.md)

A meeting planner that compares travel times from several people's departure points. Create a meeting, invite anyone through WhatsApp, email or a public link, then compare and confirm a meeting point. Guests accept before choosing their planned departure or voluntarily sharing their current location. No guest account is required.

The interface uses the original cobalt blue and mint palette, an animated introduction and a three-step planner. The application offers a French/English language choice.

## Stack

| Part | Technology |
| --- | --- |
| Browser | HTML, CSS, native JavaScript; no frontend build required |
| Map | Leaflet + OpenStreetMap tiles |
| Geography | Photon address search, OSRM car routes/matrix, Overpass nearby features |
| API | Python, FastAPI, Pydantic, HTTPX |
| Shared data | Appwrite TablesDB through server-side REST requests |
| Email | Appwrite Messaging with a configured provider; the deployed project uses Brevo SMTP |
| Local data | SQLite; optional Supabase adapter and SQL schema also included |
| Hosting | Vercel FastAPI runtime |
| Tests | pytest and a mocked Playwright browser flow |

## Run locally

Python 3.12 is the version declared in `pyproject.toml`.

```sh
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn server:app --reload
```

Open `http://127.0.0.1:8000`; interactive API documentation is at `/docs`. Local development uses SQLite when no shared database is configured.

To use Appwrite, supply `APPWRITE_ENDPOINT`, `APPWRITE_PROJECT_ID`, `APPWRITE_API_KEY` and `APPWRITE_DATABASE_ID` as server environment variables. See [.env.example](.env.example) for placeholders. Prepare the private tables in your own authorized project with `python scripts/setup_appwrite.py`. Do not copy optional Supabase placeholder values into a real environment.

The Mac launcher loads an optional local `.env.appwrite` file. The Python server does not automatically load arbitrary `.env` files. Never commit real keys, SMTP credentials, private meeting links or local databases.

## How the algorithm works

1. Generate four indicative candidate coordinates around the spherical mean of accepted departures, unless the organizer supplied their own points.
2. Build a participant-to-candidate travel-time matrix. OSRM is used for an all-car group of at most 12 people and at most 20 candidates when a complete valid response is available. Otherwise, explicitly labelled geometric estimates are used.
3. Exhaustively score every candidate and sort them:
   - **Earliest:** minimize the latest arrival (`departure availability + travel time`).
   - **Fair:** minimize the difference between the longest and shortest trips.
   - **Less travel:** minimize the sum of all travel times.

Scoring takes O(P × L), followed by O(L log L) sorting. The result is optimal only among the supplied candidates for the supplied times. The automatic coordinates are not verified cafés or public venues. Verify access or choose a real venue on the map.

**Dijkstra and Floyd–Warshall are separate educational demonstrations**, implemented in `engine.py` and exposed through `/api/algorithms/demo`. They are not locally invoked to choose the actual meeting venue. The teacher report explains their graph, formulas and complexity.

The meeting date currently acts as the earliest departure reference; the application does not solve an arrive-by deadline. Routes have no live traffic; walking, cycling and transit calculations are estimates without public transport timetables. Traffic lights show mapped locations only, without live state or countdown.

There is no fixed invitation count limit in the interface. Large groups still depend on practical storage, network and execution limits, and use estimated matrices beyond the OSRM threshold.

## Invitations and email

Public invitation links exclude the organizer's private access token. Guests' emails and GPS coordinates are omitted from guest-facing responses. The private organizer link is saved in that browser and can optionally be emailed to the creator. Treat it as a password.

WhatsApp and email share buttons prepare a message in the user's chosen app; they do not send it automatically. Optional server email receipts and venue confirmations use Appwrite Messaging. Set up an enabled email provider in Appwrite and the required server key scopes (`providers.read`, `messages.write`, `messages.read`) in addition to database access. SMTP credentials belong in the provider configuration, not the repository.

Persistence finishes before best-effort email delivery. The API reports unconfigured or failed delivery without discarding the saved meeting. Deterministic message IDs help avoid duplicate messages after technical retries. `PUBLIC_APP_URL` defines the public origin used in email links. Confirmed venue links open Google Maps; the embedded map remains OpenStreetMap.

## Deploy to Vercel

`vercel.json` selects the FastAPI runtime. Configure the Appwrite variables in the intended Vercel environments (Preview and/or Production), then:

```sh
vercel link
vercel deploy
vercel inspect <preview-url> --wait
# Deliberate main-site publication:
vercel deploy --prod
```

Set `PUBLIC_APP_URL` to the chosen canonical domain. Without shared storage on Vercel, meeting creation is disabled: serverless local disk is not used as durable storage. `.vercelignore` excludes local data, credentials and development state. The main site is [meetcool-three.vercel.app](https://meetcool-three.vercel.app/); preview deployments are separate versions. Automatic deployments from GitHub require connecting the repository to Vercel; CLI deployment alone does not create that connection.

## Validate

```sh
python -m pytest -q
node --check static/app.js
node --check static/motion.js
python -m compileall -q server.py geo.py storage.py engine.py notifications.py
```

For the browser flow, start a local server on port 8011 and run `node scripts/check_planner.mjs` with Playwright available. `MEETCOOL_TOOLKIT_PACKAGE` may point to a separate toolkit's `package.json` providing Playwright. Meeting APIs are mocked: this flow sends no real emails or invitations.

## Source layout

- `server.py`: API, validation, meeting lifecycle and candidate generation.
- `engine.py`: scoring, distance approximation and graph demonstrations.
- `geo.py`: external geographic services and bounded requests/caches.
- `storage.py`: shared and local persistence.
- `notifications.py`: Appwrite emails and Google Maps links.
- `static/`: interface and motion.
- `tests/`: backend regression tests.
- `docs/POUR_LE_PROF.md`: detailed architecture, algorithm explanation, example and deployment report.

This educational prototype was developed with Codex assistance. Its report separates implemented behavior from limitations and future work. Public map services have availability and usage limits; this is not an unrestricted production-scale routing service.

## Language choice

The FR/EN selector is available on the welcome page and in the planner. The browser saves the preference as `meetcool_language`; public invitations include the selected `lang` parameter. Interface translations run locally without an external translation API. User-entered names and addresses are preserved. Server transactional emails currently remain in French. The browser test runs the full flow in both languages.
