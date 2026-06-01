# Affiliate Engine

AI creative platform for direct-response advertising. Generates ad creatives end-to-end — research, scripts, voiceovers, images, multi-shot videos, captions, lip-sync, and a final stitched ad — across multiple AI providers, with full campaign persistence.

This is **not** a single-tool app. It's a multi-feature platform with a campaign pipeline (brief → script → storyboard → video generation → auto-edit) plus standalone tools (marketing copy, image generator, lip-sync, transcription, etc.).

---

## Two main workflows

### 1. Campaign Studio (video production pipeline)
A multi-phase, stateful pipeline that produces a finished video ad from a brief or reference. Each phase persists to Postgres and can be replayed independently.

```
draft → briefing → scripting → storyboarding → generating → editing → review → completed
```

| Phase | What happens | Backed by |
|---|---|---|
| **Briefing** | Analyze uploaded reference video/image OR text brief → extract style, palette, audience, ad arc | `ReferenceAnalyzerService` (Gemini Vision) |
| **Scripting** | Generate full ad script with hook/problem/solution/proof/CTA labels | `CampaignService.run_scripting` (Gemini) |
| **Storyboarding** | Generate shot list (hero, b-roll, action, transition, etc.) with per-shot prompts | `StoryboardService` (Gemini) |
| **Generating** | Parallel background tasks generate each shot; routed across providers by shot type | `MultiProviderVideoService` |
| **Editing** | Stitch shots, color grade, mix voiceover + music, burn captions, export | `AutoEditorService` (ffmpeg) |
| **Review** | One or more Variations produced; user picks the winner | `VariationEngine` |

### 2. Marketing Hub (text/strategy toolkit)
Six standalone tools — text outputs, no video. Cheap (Gemini text calls) and useful for cold-start research.

| Tab | What it does |
|---|---|
| **Angle Generator** | 10 marketing angles per offer using frameworks (AIDA, PAS, curiosity-gap, etc.) |
| **Ad Copy** | Platform-specific (Meta, TikTok) ad copy variations from a chosen angle |
| **Landing Page** | Generate full landing page HTML + section copy from offer details |
| **Program Finder** | Affiliate program directory search with reward/cookie/tag filters |
| **Performance** | Manual KPI tracker — input spend/clicks/conversions, get CTR, CPC, CPA, ROAS, EPC vs benchmarks |
| **Hook Library** | Stored high-performing hooks per vertical/platform with effectiveness scores |

---

## All standalone features

| Feature | Purpose | Key providers |
|---|---|---|
| **Video Creator** | Single-clip text/image-to-video via Veo 3.1 (Google AI) | Google Gemini |
| **UGC Videos** | TikTok-style avatar UGC creation | TikTok Symphony API |
| **Talking Head / Lip-Sync** | Image + audio → talking head video | Kie.ai InfiniteTalk, Replicate fallback |
| **Video Editor** | Standalone ffmpeg editor + auto-caption (Whisper) | OpenAI Whisper |
| **Video Downloader** | TikTok / YouTube downloads | yt-dlp |
| **Image Generator** | Multi-provider AI image gen | Gemini Imagen, FAL FLUX, Ideogram, OpenAI |
| **Script Generator** | Standalone ad script writer | Gemini |
| **Script to Audio** | Text-to-speech with 10 voices, multi-language | OpenAI TTS, Google Cloud TTS |
| **Transcription** | Audio/video to text | OpenAI Whisper, Deepgram |
| **Hook Analyzer** | Score and explain a video hook | Gemini Vision |
| **Video Script Analyzer** | Analyze a transcript for hooks, structure, weaknesses | Gemini |
| **Music Library** | Royalty-free music search | Pixabay |
| **Stock Footage** | Stock clip search | Pexels |
| **Characters / Scene Settings** | Reusable assets — character portraits + locations with consistency prompts | Gemini Vision (auto-analysis on upload) |
| **Variations** | Create alternate edits/styles of a finished campaign | `VariationEngine` |
| **Analytics** | Cost tracking, generation history, per-vertical metrics | Internal DB |
| **Admin Panel** | User management, AI suggestion review, model registry | Internal DB |
| **Auth** | JWT-based auth, role-based permissions, audit log | Internal DB |

---

## Provider stack & routing

Video shots are routed to the best provider per shot type. Each shot type has an ordered fallback chain — first available provider wins.

| Shot type | Primary | Fallbacks |
|---|---|---|
| hero, lip_sync | runway-gen4 | veo-3.1, higgsfield-v1 |
| spokesperson | runway-gen4 | higgsfield-v1, veo-3.1 |
| action, motion | runway-gen4 | kling-v3, higgsfield-v1 |
| b_roll | runway-gen4 | hailuo-02, wan-2.2 |
| transition | runway-gen4 | wan-2.2, hailuo-02 |

**Provider mapping:**
- `runway-gen4` → Kie.ai (`/api/v1/runway/generate`, poll at `/api/v1/runway/record-detail`)
- `veo-3.1` / `veo-3.1-fast` → Google AI Studio via `VideoCreatorService`
- `higgsfield-v1`, `kling-v3`, `wan-2.2`, `hailuo-02`, `seedance-2` → Higgsfield platform (`https://platform.higgsfield.ai`)
- Text-to-video on Higgsfield is routed to `bytedance/seedance/v1/pro/text-to-video` (only confirmed T2V slug on the official REST API)
- Image-to-video on Higgsfield uses model-specific slugs (`kling-video/v2.1/pro/image-to-video`, `higgsfield-ai/dop/standard`, etc.)

---

## Tech stack

**Backend** — FastAPI (Python 3.12), SQLAlchemy + Alembic, PostgreSQL, httpx, ffmpeg, pydub. Sync HTTP via `httpx` (provider calls run inside async background tasks).

**Frontend** — Next.js 14, React 18, TypeScript, Tailwind CSS, Axios.

**Storage** — Local filesystem for generated assets (`generated_videos/`, `generated_images/`, `uploads/`) with S3 upload via `StorageService` for production.

**Deployment** — Render (web service for backend, separate static deploy for frontend). Postgres database also on Render.

---

## Quick start

### Prerequisites
- Python 3.12+
- Node.js 18+
- ffmpeg installed on PATH
- Postgres (or sqlite for local dev)
- At minimum: `GEMINI_API_KEY` and `OPENAI_API_KEY`

### Backend

```bash
cd backend
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env       # then edit
alembic upgrade head        # run migrations
uvicorn app.main:app --reload --port 8000
```

API docs: http://localhost:8000/docs

### Frontend

```bash
cd frontend
npm install
echo "NEXT_PUBLIC_API_URL=http://localhost:8000/api/v1" > .env.local
npm run dev
```

App: http://localhost:3000

---

## Environment variables

### Critical (system fails without these)
| Var | Purpose |
|---|---|
| `DATABASE_URL` | Postgres connection string |
| `JWT_SECRET_KEY` | Auth token signing |
| `GEMINI_API_KEY` | Scripts, briefs, image gen, vision analysis, marketing hub |
| `OPENAI_API_KEY` | TTS, Whisper transcription, fallback image gen |

### High-impact (unlocks major features)
| Var | Unlocks |
|---|---|
| `KIE_API_KEY` | Runway Gen-4 video, Veo via Kie.ai, FLUX images, InfiniteTalk lip-sync |
| `HIGGSFIELD_API_KEY` + `HIGGSFIELD_API_SECRET` | Higgsfield video models (Kling, Seedance, Hailuo, Wan, DoP) |
| `REPLICATE_API_TOKEN` | Lip-sync fallback when Kie.ai unavailable |
| `TIKTOK_ACCESS_TOKEN` | TikTok UGC video creation (OAuth, not a simple key) |
| `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_S3_BUCKET`, `AWS_REGION` | S3 upload for generated assets |

### Optional (graceful fallback if missing)
| Var | Unlocks |
|---|---|
| `PIXABAY_API_KEY` | Music Library (returns empty if missing) |
| `PEXELS_API_KEY` | Stock Footage (returns empty if missing) |
| `FAL_API_KEY` | FAL FLUX image fallback |
| `IDEOGRAM_API_KEY` | Ideogram image fallback |
| `DEEPGRAM_API_KEY` | Deepgram transcription alternative |

### Frontend
| Var | Purpose |
|---|---|
| `NEXT_PUBLIC_API_URL` | Backend base URL — defaults to `http://localhost:8000/api/v1` |

---

## Database schema (high level)

- **users**, **roles**, **permissions** — auth
- **campaigns** — campaign metadata, analyzed_brief, script, storyboard, status
- **shots** — per-shot prompt, model_id, duration, video_path, video_url, status, cost
- **variations** — alternate edits of a campaign
- **characters**, **scene_settings** — reusable creative assets with consistency prompts
- **images** — generated images with prompt + provider + cost
- **job_results** — sync job history (scripts, angles, ad copy, etc.)
- **learning_records** — feedback + performance metrics for the learning engine
- **audit_logs** — all auth + admin actions
- **ai_suggestions** — admin-reviewable AI improvement proposals

Migrations via Alembic. See `backend/alembic/versions/`.

---

## API surface

29 route files, ~150 endpoints, all mounted under `/api/v1`. Highlights:

```
POST   /api/v1/auth/register, /login
GET/POST /api/v1/campaigns         # full pipeline
POST   /api/v1/campaigns/{id}/brief, /script, /storyboard, /generate, /edit
GET/POST /api/v1/characters, /scene-settings
POST   /api/v1/marketing/angles/generate
POST   /api/v1/marketing/ad-copy/generate
POST   /api/v1/marketing/landing-page/generate
GET    /api/v1/research/affiliate-search
GET/POST /api/v1/research/hooks
POST   /api/v1/research/performance/record
POST   /api/v1/video/generate, /video/long/create
POST   /api/v1/lip-sync/generate
POST   /api/v1/speech/generate
POST   /api/v1/transcription/transcribe-file
POST   /api/v1/images/generate
POST   /api/v1/video-edit/edit, /auto-caption
POST   /api/v1/tiktok/videos/create
GET    /api/v1/analytics/overview, /billing, /time-series
GET    /api/v1/admin/dashboard
```

Full OpenAPI docs at `/docs` when backend is running.

---

## Project structure

```
affiliate-engine/
├── backend/
│   ├── app/
│   │   ├── main.py
│   │   ├── config.py
│   │   ├── database.py
│   │   ├── middleware/         # auth, CORS, audit
│   │   ├── models/             # SQLAlchemy models
│   │   ├── routes/             # 29 route files
│   │   ├── services/           # 46 service modules
│   │   └── schemas.py
│   ├── alembic/                # DB migrations
│   ├── generated_videos/       # output (gitignored)
│   ├── generated_images/
│   ├── uploads/
│   └── requirements.txt
├── frontend/
│   ├── app/
│   ├── components/             # 23 feature components
│   └── package.json
└── README.md
```

---

## Production deployment

Currently deployed to Render:
- Backend web service (Python, Postgres-backed)
- Frontend static deploy
- Postgres managed database

Background tasks run in-process via FastAPI's `BackgroundTasks`. Long-running video generation polls survive instance restarts because shot status is persisted to DB; on restart, `start_generation` resets stuck `generating` shots back to `pending` and re-queues them.

---

## Known limitations & runbook

- **Video generation is provider-dependent.** Code is correct against documented provider contracts (Kie.ai docs, Higgsfield JS SDK), but each provider has its own credit/quota system. A 402 on Kie.ai means top up balance; a 404 on a Higgsfield slug means try a different model.
- **Higgsfield text-to-video** has limited model coverage on the official REST API — only Seedance T2V is confirmed. All other Higgsfield T2V routes either fall back to Seedance or 404.
- **TikTok UGC** requires a full OAuth flow, not just an API key. Setting `TIKTOK_ACCESS_TOKEN` to a hand-issued token works for short-lived testing only.
- **No automated competitor ad scraping.** `ReferenceAnalyzerService` analyzes ONE uploaded reference; bulk competitor discovery (Facebook Ad Library, etc.) is not built in.
- **Marketing Hub job persistence** wraps `JobService.save_sync_result` with explicit error logging — DB write failures no longer disappear silently.

---

## License

Proprietary — Pear Media LLC.
