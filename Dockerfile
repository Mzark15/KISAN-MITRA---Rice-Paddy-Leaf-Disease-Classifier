FROM python:3.11-slim

WORKDIR /app

# No system packages needed — Pillow ships pre-built wheels.
# libgl1/libglib2.0-0 are only required for OpenCV, which this project does not use.

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ backend/
COPY frontend/ frontend/
RUN mkdir -p /app/data

ENV MODEL_PATH=/app/backend/models/paddy_disease_model.tflite
ENV PORT=8000

EXPOSE 8000

WORKDIR /app/backend
CMD ["python", "main.py"]
