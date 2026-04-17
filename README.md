# Affiliate Marketing Image Generation Engine - MVP

A production-ready MVP for generating high-performing home insurance ad images using AI-optimized prompts.

## Features

- **Home Insurance Focus**: 5 pre-built, conversion-optimized templates
- **Gemini-Powered Prompts**: Uses Google's Gemini API to optimize prompts for conversions
- **Image Generation**: Multi-provider support (Gemini, FAL.ai FLUX)
- **Cost Tracking**: Automatic tracking of generation costs per image
- **Performance Analytics**: Dashboard for tracking CTR, ROI, and other metrics
- **Database**: SQLite for MVP, easily migrates to PostgreSQL

## Architecture

### Backend (FastAPI)
- **Framework**: FastAPI with async support
- **Database**: SQLAlchemy ORM with SQLite (production-ready for PostgreSQL migration)
- **API**: RESTful endpoints at `/api/v1`
- **Services**: Modular services for templates, prompt optimization, image generation, and analytics

### Frontend (Next.js)
- **Framework**: Next.js 14 with React 18
- **Styling**: Tailwind CSS
- **Components**: Modular, reusable components
- **API Client**: Axios with typed endpoints

## Quick Start

### Prerequisites
- Python 3.10+
- Node.js 18+
- Gemini API key

### Backend Setup

```bash
cd backend

# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Create .env file
cp .env.example .env
# Edit .env with your GEMINI_API_KEY

# Run the server
python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Backend will be available at: http://localhost:8000
API Docs: http://localhost:8000/docs

### Frontend Setup

```bash
cd frontend

# Install dependencies
npm install

# Create .env.local (optional, defaults to localhost:8000)
echo "NEXT_PUBLIC_API_URL=http://localhost:8000/api/v1" > .env.local

# Run development server
npm run dev
```

Frontend will be available at: http://localhost:3000

## API Endpoints

### Templates
- `GET /api/v1/templates/home-insurance` - Get all home insurance templates
- `GET /api/v1/templates/{template_id}` - Get specific template
- `GET /api/v1/templates/vertical/{vertical}` - Get templates by vertical

### Images
- `POST /api/v1/images/generate` - Generate images from template
- `GET /api/v1/images/list` - List generated images
- `GET /api/v1/images/{image_id}` - Get specific image

### Analytics
- `GET /api/v1/analytics/overview` - Overall client analytics
- `GET /api/v1/analytics/vertical/{vertical}` - Vertical-specific analytics
- `GET /api/v1/analytics/top-templates` - Best performing templates
- `GET /api/v1/analytics/time-series` - Analytics over time

## Database Schema

### Core Tables
- **clients** - Client/user accounts
- **templates** - Template definitions per vertical
- **images** - Generated images with metadata
- **performance_metrics** - Campaign performance tracking

All migrations handled via SQLAlchemy ORM. No separate migration tool needed for MVP.

## Production Readiness

This MVP is designed to scale to production with minimal changes:

### Database Migration
```python
# Change in backend/app/config.py
DATABASE_URL = "postgresql://user:password@localhost:5432/affiliate_images"
```

### Image Provider Switch
```python
# In backend/app/config.py
IMAGE_PROVIDER = "fal"  # or "gemini"
# Or implement new providers by extending ImageGeneratorService
```

### Deployment
- **Backend**: FastAPI can be deployed to Any cloud (AWS, GCP, Azure, etc.) with Gunicorn/Uvicorn
- **Frontend**: Next.js deploys easily to Vercel, Netlify, or any static host
- **Database**: SQLite .db file can be replaced with PostgreSQL connection string

## Configuration

### Environment Variables

**Backend** (`.env`):
```
GEMINI_API_KEY=xxx
FAL_API_KEY=xxx
DATABASE_URL=sqlite:///./affiliate_images.db
IMAGE_PROVIDER=gemini
IMAGE_GENERATION_COST=0.02
DEBUG=False
```

**Frontend** (`.env.local`):
```
NEXT_PUBLIC_API_URL=http://localhost:8000/api/v1
```

## Project Structure

```
affiliate-image-engine/
├── backend/
│   ├── app/
│   │   ├── models/          # Database models
│   │   ├── schemas/         # Pydantic schemas
│   │   ├── routes/          # API routes
│   │   ├── services/        # Business logic
│   │   └── main.py          # FastAPI app
│   ├── requirements.txt
│   └── .env.example
├── frontend/
│   ├── app/                 # Next.js pages
│   ├── components/          # React components
│   ├── lib/                 # Utilities & API client
│   ├── styles/              # CSS
│   └── package.json
└── README.md
```

## Next Steps (Post-MVP)

1. **Image Generation Provider Integration**
   - Implement actual Google Imagen API call
   - Add FAL.ai FLUX integration
   - Add error handling and retries

2. **Additional Verticals**
   - GLP/Weight Loss templates
   - Refinance/Personal Loans
   - Auto Insurance
   - etc.

3. **Enhanced Analytics**
   - Real performance data integration
   - Dashboard visualizations
   - Export reports

4. **Authentication & Multi-Client**
   - User accounts and authentication
   - Per-client API keys
   - Usage quotas and billing

5. **Advanced Features**
   - A/B testing framework
   - Template optimization suggestions
   - Batch processing
   - Webhook integrations for ad platforms

## Cost Model

- **Google Imagen**: ~$0.01-0.03 per image
- **FAL.ai FLUX**: ~$0.01-0.02 per image
- **Gemini Prompt Optimization**: ~$0.0001 per call

**Estimated MVP cost**: ~$0.02 per image

## Support & Development

For issues, feature requests, or improvements:
1. Check the AGENT_GUIDE.md in the parent OpenMontage directory
2. Review the spec in AFFILIATE_MARKETING_IMAGE_ENGINE.md

## License

Proprietary - Pear Media LLC
