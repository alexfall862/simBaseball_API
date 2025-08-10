FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# System deps for psycopg2 if not using binary wheel
RUN apt-get update && apt-get install -y build-essential libpq-dev && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py .

# Expose port
EXPOSE 8080

# Use gunicorn in production (multi-worker, threaded, reasonable timeout)
CMD ["gunicorn", "-w", "2", "--threads", "4", "--timeout", "30", "-b", "0.0.0.0:8080", "app:create_app()"]
