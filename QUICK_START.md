# Quick Start Guide

Get the Affiliate Image Engine running in 5 minutes.

## Prerequisites

- Python 3.10+
- Node.js 18+
- Gemini API key

## 1. Run Setup Script

```bash
cd affiliate-image-engine
chmod +x setup.sh
./setup.sh
```

This will:
- Check Python and Node.js
- Create Python virtual environment
- Install all dependencies
- Create config files

## 2. Configure Gemini API

```bash
# Edit backend/.env
cd backend
nano .env  # or use your preferred editor

# Add your Gemini API key:
# GEMINI_API_KEY=your_key_here

cd ..
```

Get your key from: https://makersuite.google.com/app/apikey

## 3. Start Backend

```bash
cd backend
source venv/bin/activate  # On Windows: venv\Scripts\activate
python -m uvicorn app.main:app --reload
```

✓ Backend running at: http://localhost:8000
✓ API docs at: http://localhost:8000/docs

## 4. Start Frontend (New Terminal)

```bash
cd frontend
npm run dev
```

✓ Frontend running at: http://localhost:3000

## 5. Test the Application

### Via Browser
1. Open http://localhost:3000
2. Select a home insurance template
3. Click "Generate Images"
4. View generated images in the Gallery tab
5. Check Analytics tab for metrics

### Via API

```bash
# Health check
curl http://localhost:8000/api/v1/health

# Get templates
curl http://localhost:8000/api/v1/templates/home-insurance

# Generate images
curl -X POST http://localhost:8000/api/v1/images/generate?client_id=demo-client \
  -H "Content-Type: application/json" \
  -d '{
    "vertical": "home_insurance",
    "template_id": "home_insurance_family_safety_001",
    "count": 5
  }'

# Get analytics
curl http://localhost:8000/api/v1/analytics/overview?client_id=demo-client
```

## Database

The application uses SQLite by default. Database file: `backend/affiliate_images.db`

Database is initialized automatically on first run with home insurance templates.

## Environment Variables

### Backend (backend/.env)

```
GEMINI_API_KEY=your_key_here
DATABASE_URL=sqlite:///./affiliate_images.db
IMAGE_PROVIDER=gemini
IMAGE_GENERATION_COST=0.02
DEBUG=True
```

### Frontend (frontend/.env.local) - Optional

```
NEXT_PUBLIC_API_URL=http://localhost:8000/api/v1
```

## Troubleshooting

### Backend won't start
```bash
# Ensure you're in the virtual environment
source venv/bin/activate

# Check Python version
python --version  # Should be 3.10+

# Reinstall dependencies
pip install -r requirements.txt
```

### Frontend issues
```bash
# Clear cache and reinstall
rm -rf node_modules package-lock.json
npm install
npm run dev
```

### API connection errors
- Ensure backend is running on port 8000
- Check CORS is enabled in backend/app/config.py
- Check NEXT_PUBLIC_API_URL in frontend/.env.local

### Database errors
```bash
# Remove old database and let it reinitialize
rm backend/affiliate_images.db

# Restart backend
python -m uvicorn app.main:app --reload
```

## Next Steps

1. **Add More Templates**: Edit `backend/app/services/vertical_templates.py`
2. **Integrate Image Generation**: Update `backend/app/services/image_generator.py` with actual provider API calls
3. **Add Authentication**: Implement user login and per-user API keys
4. **Deploy**: See DEPLOYMENT.md for cloud deployment options

## Architecture Overview

```
┌─────────────────┐
│   Frontend      │
│   (Next.js)     │  ← http://localhost:3000
└────────┬────────┘
         │ Axios HTTP Requests
         ▼
┌─────────────────┐
│   Backend API   │
│   (FastAPI)     │  ← http://localhost:8000
└────────┬────────┘
         │ SQLAlchemy ORM
         ▼
┌─────────────────┐
│   SQLite DB     │
│ (affiliate_     │
│  images.db)     │
└─────────────────┘
```

## Common Tasks

### Generate a batch of images
```python
# backend/test_generation.py
import asyncio
from app.services import ImageGeneratorService, PromptOptimizerService
from app.database import SessionLocal

async def generate_batch():
    db = SessionLocal()
    service = ImageGeneratorService()
    prompt_optimizer = PromptOptimizerService()
    
    template = db.query(Template).first()
    if template:
        optimized = prompt_optimizer.optimize_prompt(
            template.prompt_base,
            "home_insurance"
        )
        
        images = await service.generate_batch(
            client_id="demo-client",
            template_id=template.id,
            prompts=[optimized] * 5,
            vertical="home_insurance"
        )
        
        print(f"Generated {len(images)} images")

asyncio.run(generate_batch())
```

### Check database contents
```bash
# Open SQLite shell
sqlite3 backend/affiliate_images.db

# View templates
SELECT template_name, vertical, success_rate FROM templates;

# View images
SELECT id, vertical, cost_usd, created_at FROM images LIMIT 10;

# Exit
.quit
```

## Support

For issues or questions, check:
- API docs: http://localhost:8000/docs (Swagger UI)
- README.md for architecture details
- DEPLOYMENT.md for production setup
