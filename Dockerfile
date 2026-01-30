FROM python:3.11-slim

WORKDIR /app

# Install system dependencies for Playwright
RUN apt-get update && apt-get install -y \
    wget \
    gnupg \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright browsers
RUN playwright install chromium && playwright install-deps chromium

# Copy application code
COPY tiktok_monitor.py tiktok_collections.py viewer.py viewer.html ./
COPY tests/ ./tests/

# Create volume mount points
VOLUME ["/app/config", "/app/downloads"]

# Expose viewer port (configurable via VIEWER_PORT env var, default 8425)
EXPOSE 8425

# Default command runs the entrypoint script
COPY docker-entrypoint.sh /docker-entrypoint.sh
RUN chmod +x /docker-entrypoint.sh

ENTRYPOINT ["/docker-entrypoint.sh"]
