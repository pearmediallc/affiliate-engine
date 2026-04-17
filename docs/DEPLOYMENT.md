# Deployment Guide

Production deployment options for the Affiliate Image Engine MVP.

## Overview

The MVP is designed to scale from SQLite+local to production easily:

```
MVP (Development)          Production (Scalable)
├─ SQLite                  ├─ PostgreSQL
├─ Local files             ├─ AWS S3 / Cloud Storage
├─ Single server           ├─ Kubernetes / App Engine
└─ Mock image generation   └─ Real API providers
```

## Pre-Deployment Checklist

- [ ] Set environment variables for production
- [ ] Switch database to PostgreSQL
- [ ] Configure real image generation providers
- [ ] Set up cloud storage (S3)
- [ ] Enable authentication
- [ ] Configure CORS for your domain
- [ ] Set up SSL/TLS certificates
- [ ] Configure logging and monitoring
- [ ] Set up database backups
- [ ] Load test the application

## Backend Deployment

### Option 1: Google Cloud Run (Recommended)

Fast, serverless, automatic scaling.

```bash
# 1. Create GCP project and set up Cloud Run

# 2. Update production config
# backend/app/config.py
DATABASE_URL = "postgresql://user:pass@host/db"
IMAGE_PROVIDER = "gemini"  # or "fal"

# 3. Create .env.prod with production secrets
# (Do NOT commit to git)

# 4. Build and push to Cloud Run
gcloud builds submit --tag gcr.io/YOUR_PROJECT/affiliate-engine
gcloud run deploy affiliate-engine \
  --image gcr.io/YOUR_PROJECT/affiliate-engine \
  --platform managed \
  --region us-central1 \
  --set-env-vars GEMINI_API_KEY=${GEMINI_API_KEY},DATABASE_URL=${DATABASE_URL}
```

### Option 2: AWS EC2 + RDS

More control, traditional setup.

```bash
# 1. Launch EC2 instance (t3.medium or larger)
# 2. Install Docker
# 3. Set up RDS PostgreSQL database
# 4. Deploy with Docker:

docker pull YOUR_REGISTRY/affiliate-engine:latest
docker run -d \
  -p 8000:8000 \
  -e DATABASE_URL="postgresql://..." \
  -e GEMINI_API_KEY="..." \
  YOUR_REGISTRY/affiliate-engine:latest
```

### Option 3: Docker Compose (Self-Hosted)

For VPS or on-premise deployment.

```bash
# 1. Copy project to server
# 2. Create production .env

cat > .env.prod << EOF
DATABASE_URL=postgresql://user:pass@postgres:5432/affiliate_images
GEMINI_API_KEY=your_key
FAL_API_KEY=your_key
IMAGE_PROVIDER=gemini
DEBUG=False
CORS_ORIGINS=["https://yourdomain.com"]
EOF

# 3. Run with docker-compose
docker-compose -f docker-compose.prod.yml up -d
```

### Option 4: Traditional Linux (Ubuntu/Debian)

```bash
# 1. Install Python, Node, Nginx, PostgreSQL
sudo apt update && sudo apt install -y python3.10 nodejs postgresql nginx

# 2. Clone repository
git clone https://github.com/yourrepo/affiliate-image-engine
cd affiliate-image-engine

# 3. Setup backend with systemd
sudo useradd -m affiliate
sudo chown -R affiliate:affiliate .

# 4. Create systemd service
sudo tee /etc/systemd/system/affiliate-engine.service > /dev/null <<EOF
[Unit]
Description=Affiliate Image Engine
After=network.target

[Service]
User=affiliate
WorkingDirectory=/home/affiliate/affiliate-image-engine/backend
Environment="PATH=/home/affiliate/affiliate-image-engine/backend/venv/bin"
ExecStart=/home/affiliate/affiliate-image-engine/backend/venv/bin/gunicorn -w 4 -k uvicorn.workers.UvicornWorker app.main:app --bind 0.0.0.0:8000

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl enable affiliate-engine
sudo systemctl start affiliate-engine

# 5. Setup Nginx reverse proxy
sudo tee /etc/nginx/sites-available/affiliate-engine > /dev/null <<EOF
server {
    listen 80;
    server_name your.domain;
    client_max_body_size 50M;

    location / {
        proxy_pass http://localhost:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
EOF

sudo ln -s /etc/nginx/sites-available/affiliate-engine /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl restart nginx
```

## Database Migration

### SQLite → PostgreSQL

```bash
# 1. Install PostgreSQL adapter
pip install psycopg2-binary

# 2. Update DATABASE_URL in .env
# SQLite: sqlite:///./affiliate_images.db
# PostgreSQL: postgresql://user:password@localhost/affiliate_images

# 3. Run database initialization
python -c "from app.database import init_db; init_db()"

# 4. (Optional) Migrate existing data
# Use SQLAlchemy migration tools or manual export/import
```

## Frontend Deployment

### Option 1: Vercel (Recommended)

Zero-config, automatic scaling.

```bash
# 1. Push to GitHub
git push origin main

# 2. Connect to Vercel
# Go to vercel.com, import GitHub project

# 3. Set environment variable
# Project Settings → Environment Variables
# NEXT_PUBLIC_API_URL = https://your-api-domain.com/api/v1

# 4. Deploy
# Automatic on push, or manual from Vercel dashboard
```

### Option 2: Netlify

Similar to Vercel, static hosting with serverless functions.

```bash
# 1. Connect GitHub to Netlify
# 2. Build settings:
#    Build command: npm run build
#    Publish directory: out
# 3. Netlify functions for API proxy (if needed)
```

### Option 3: AWS S3 + CloudFront

Static hosting with CDN.

```bash
npm run build

# Upload to S3
aws s3 sync out/ s3://your-bucket --delete

# CloudFront will serve from S3
```

### Option 4: Docker

```bash
# Build Next.js image
docker build -t affiliate-engine-frontend frontend/

# Run
docker run -p 3000:3000 \
  -e NEXT_PUBLIC_API_URL=https://api.yourdomain.com/api/v1 \
  affiliate-engine-frontend
```

## Environment Configuration

### Production .env Example

```env
# Database
DATABASE_URL=postgresql://user:pass@db.example.com:5432/affiliate_images

# API Keys (use secrets manager in production!)
GEMINI_API_KEY=production_key_here
FAL_API_KEY=production_key_here

# Image Generation
IMAGE_PROVIDER=gemini
IMAGE_GENERATION_COST=0.02

# Security
DEBUG=False
CORS_ORIGINS=["https://yourdomain.com", "https://www.yourdomain.com"]

# Storage (if using cloud storage)
AWS_ACCESS_KEY_ID=your_key
AWS_SECRET_ACCESS_KEY=your_secret
AWS_S3_BUCKET=affiliate-images-prod

# Email (for notifications)
SMTP_SERVER=smtp.gmail.com
SMTP_PORT=587
SMTP_USERNAME=your_email
SMTP_PASSWORD=your_password

# Logging
LOG_LEVEL=INFO
LOG_FILE=/var/log/affiliate-engine/app.log

# Performance
WORKERS=4
WORKER_CLASS=uvicorn
MAX_REQUESTS=1000
```

## Image Storage

### Local (Current MVP)
- Images saved to local filesystem
- Issue: Not scalable for multiple servers

### AWS S3 (Recommended)
```python
# In backend/app/services/image_generator.py
import boto3
from botocore.exceptions import ClientError

class S3ImageStorage:
    def __init__(self, bucket_name):
        self.s3_client = boto3.client('s3')
        self.bucket = bucket_name

    def upload_image(self, file_path, key):
        try:
            self.s3_client.upload_file(file_path, self.bucket, key)
            url = f"https://{self.bucket}.s3.amazonaws.com/{key}"
            return url
        except ClientError as e:
            raise Exception(f"Upload failed: {e}")
```

### Google Cloud Storage
```python
from google.cloud import storage

class GCSImageStorage:
    def __init__(self, bucket_name):
        self.client = storage.Client()
        self.bucket = self.client.bucket(bucket_name)

    def upload_image(self, file_path, key):
        blob = self.bucket.blob(key)
        blob.upload_from_filename(file_path)
        return blob.public_url
```

## Monitoring & Logging

### Logging Setup
```python
# backend/app/config.py - Add logging configuration
import logging
from logging.handlers import RotatingFileHandler

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        RotatingFileHandler('app.log', maxBytes=10485760, backupCount=5),
        logging.StreamHandler()
    ]
)
```

### Monitoring Services
- **Sentry** (error tracking): Configure in FastAPI
- **DataDog** (metrics): Agent-based monitoring
- **Prometheus** (metrics): Expose `/metrics` endpoint
- **ELK Stack** (logs): Centralized logging

## Performance Optimization

### Backend
```python
# 1. Connection pooling
DATABASE_URL = "postgresql://user:pass@db/myapp?sslmode=require&application_name=affiliate_engine"

# 2. Caching (Redis)
from redis import Redis
cache = Redis(host='localhost', port=6379)

# 3. Database indexes (already in schema)

# 4. API Rate Limiting
from slowapi import Limiter
limiter = Limiter(key_func=get_remote_address)

# 5. Async operations (already using async)
```

### Frontend
```javascript
// Next.js already optimizes:
// - Automatic code splitting
// - Image optimization
// - Static generation where possible
// - API routes for backend proxy

// Additional optimizations:
// - Enable static export if not using SSR
// - Use Image component for optimization
// - Implement incremental static regeneration
```

## SSL/TLS Certificates

### Let's Encrypt (Free)
```bash
# Using Certbot with Nginx
sudo apt install certbot python3-certbot-nginx
sudo certbot certonly --nginx -d yourdomain.com
```

### Auto-renewal
```bash
sudo systemctl enable certbot.timer
sudo systemctl start certbot.timer
```

## Database Backups

### PostgreSQL Backup Strategy
```bash
# Daily backup script
#!/bin/bash
BACKUP_DIR="/backups/affiliate-engine"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)

pg_dump affiliate_images > $BACKUP_DIR/backup_$TIMESTAMP.sql
gzip $BACKUP_DIR/backup_$TIMESTAMP.sql

# Upload to S3
aws s3 cp $BACKUP_DIR/backup_$TIMESTAMP.sql.gz s3://backup-bucket/

# Keep only 30 days
find $BACKUP_DIR -name "backup_*.sql.gz" -mtime +30 -delete

# Add to crontab
0 2 * * * /path/to/backup-script.sh
```

## Load Testing

Before going to production, test with realistic load:

```bash
# Using Apache Bench
ab -n 1000 -c 10 http://localhost:8000/api/v1/health

# Using k6
k6 run load-test.js

# Using locust
locust -f locustfile.py -u 100 -r 10 --headless
```

## Security Checklist

- [ ] Use HTTPS everywhere
- [ ] Set secure CORS origins
- [ ] Enable CSRF protection
- [ ] Use environment variables for secrets
- [ ] Implement rate limiting
- [ ] Add request validation
- [ ] Enable database encryption
- [ ] Use prepared statements (SQLAlchemy does this)
- [ ] Implement API key rotation
- [ ] Regular security audits
- [ ] Keep dependencies updated

## Cost Estimation

### Monthly Production Costs

| Component | Size | Cost |
|-----------|------|------|
| Compute (Cloud Run) | 1000 req/day | $10-50 |
| Database (PostgreSQL) | 10GB | $15-100 |
| Storage (S3) | 1000 images/month | $1-10 |
| Image generation | 1000 images | $20 |
| **Total** | | **$46-180** |

## Support & Monitoring

### Health Checks
```bash
curl https://yourdomain.com/api/v1/health
```

### Error Tracking
- Set up Sentry for error reporting
- Configure email alerts for critical errors

### Performance Monitoring
- Database query performance
- API response times
- Image generation latency
