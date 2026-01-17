FROM python:3.10-slim

WORKDIR /app

# Copy requirement files
COPY requirements.txt .

# Install dependencies
# We install fontconfig and some fonts for Matplotlib/Pillow
RUN apt-get update && apt-get install -y \
    fonts-liberation \
    fonts-dejavu \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir -r requirements.txt

# Copy the entire project
COPY . /app

# Define Environment Variable for config
ENV CONFIG_PATH=/app/config.yaml

# Expose Web Port
EXPOSE 8000

# Run the FastAPI app
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]