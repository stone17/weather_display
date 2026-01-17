FROM python:3.11-slim

WORKDIR /app

# Install System Deps
RUN apt-get update && apt-get install -y \
    fonts-liberation \
    fonts-dejavu \
    && rm -rf /var/lib/apt/lists/*

# Install Python Deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy Project Structure
COPY app /app/app
COPY backend /app/backend

# Create placeholders for config and cache (mounted at runtime)
# We don't COPY them because we want to use the volumes
RUN mkdir /app/config && mkdir /app/cache

# Expose Web Port
EXPOSE 8000

# Run
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]