FROM python:3.12-slim

WORKDIR /app

# Install system deps (ffmpeg for video/audio, gcc for psycopg2)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg gcc curl \
    && rm -rf /var/lib/apt/lists/*

# Install yt-dlp for video downloading
RUN pip install --no-cache-dir yt-dlp

# Copy requirements and install
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application
COPY . .

# Create runtime directories
RUN mkdir -p generated_images downloads

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
