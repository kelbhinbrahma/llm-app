# Start from a small official Python image
FROM python:3.11-slim

# Don't create .pyc files, and print logs immediately
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /code

# Install libraries first. Docker caches this layer, so it is only
# re-run when requirements.txt changes (faster rebuilds).
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the application code
COPY app ./app

# Run as a normal user, not root (safer)
RUN useradd --create-home appuser
USER appuser

EXPOSE 8000

# 2 worker processes inside each container
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
