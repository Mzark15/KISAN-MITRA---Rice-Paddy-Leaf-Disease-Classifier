FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ backend/
COPY frontend/ frontend/
RUN mkdir -p /app/data /app/backend/models

EXPOSE 8000

WORKDIR /app/backend
CMD ["python", "main.py"]
