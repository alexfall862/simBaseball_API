FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# optional, but nice for health monitoring
EXPOSE 8080

# Use $PORT if provided, otherwise 8080 locally
CMD ["/bin/sh","-lc","exec gunicorn -w ${GUNICORN_WORKERS:-2} --threads ${GUNICORN_THREADS:-4} --timeout ${GUNICORN_TIMEOUT:-45} --log-level info --access-logfile - -b 0.0.0.0:${PORT:-8080} 'app:create_app()'"]
