# Kisan Mitra - Phase 1 MVP (Disease Detection)

## Overview
A minimal, working web-based MVP for an AI-powered paddy disease diagnosis tool.

## Setup

### Install dependencies
```bash
pip install -r requirements.txt
```

### Run backend
```bash
cd backend
python main.py
```

### Run frontend
Open `frontend/index.html` in your browser.

## API Endpoints

### POST /diagnose
Accepts an uploaded leaf image and returns disease diagnosis.

### GET /diseases
Returns static JSON with disease information and treatment options.

## Notes
- The current implementation uses a placeholder for model inference (returns random values). Replace this with your actual TFLite/MobileNetV2 model.
- CORS is enabled for local frontend testing.
