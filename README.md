# Kisan Mitra — Phase 1 MVP (Disease Detection)

Minimal web-based MVP for AI-powered paddy disease diagnosis. Built for field testing with farmers (weeks 4–9).

## Quick start (single command)

**Docker (recommended):**
```bash
docker compose up --build
```

**Local (no Docker):**
```bash
chmod +x start.sh && ./start.sh
```

Open **http://localhost:8000** in your browser.

## Model setup

Place your trained **Paddy Doctor MobileNet** TFLite model at:

```
backend/models/paddy_disease_model.tflite
```

See [backend/models/README.md](backend/models/README.md) for class order and input specs.

**Have a Keras `.h5` model?** Convert it:
```bash
python scripts/convert_to_tflite.py path/to/your_model.h5
```

Without the model file, `/diagnose` returns HTTP 503. `/diseases` and `/health` still work.

**macOS (Apple Silicon):** `tflite-runtime` is not available via pip. Use `./start.sh` (installs TensorFlow as fallback) or `pip install tensorflow` manually.

## API

| Method | Endpoint    | Description                                      |
|--------|-------------|--------------------------------------------------|
| GET    | `/health`   | Service status and whether model is loaded       |
| GET    | `/diseases` | Static JSON: cause, severity, treatments         |
| POST   | `/diagnose` | Upload leaf image → disease + confidence + treatment |

### POST /diagnose

- **Body:** `multipart/form-data` with field `image`
- **Response:**
```json
{
  "disease": "Brown Spot",
  "confidence": 87.42,
  "treatment": {
    "cause": "...",
    "severity_levels": ["Low", "Medium", "High"],
    "organic_treatment": "...",
    "chemical_treatment": "..."
  }
}
```

## Disease classes (Paddy Doctor — 13 classes)

Bacterial Leaf Blight · Bacterial Leaf Streak · Bacterial Panicle Blight · Black Stem Borer · Blast · Brown Spot · Downy Mildew · Hispa · Leaf Roller · Tungro · White Stem Borer · Yellow Stem Borer · Normal

Based on the [Paddy Doctor dataset](https://paddydoc.github.io/) (Petchiammal et al., CODS-COMAD 2023).

## Project structure

```
backend/
  main.py           # FastAPI app + static frontend serve
  inference.py      # TFLite model loading & prediction
  diseases.json     # Treatment knowledge base
  models/           # Place .tflite model here
frontend/
  index.html        # Single-page upload/capture UI
docker-compose.yml
Dockerfile
start.sh
```

## Environment variables

| Variable           | Default                                      |
|--------------------|----------------------------------------------|
| `MODEL_PATH`       | `backend/models/paddy_disease_model.tflite`  |
| `MODEL_INPUT_SIZE` | `256`                                        |
| `PORT`             | `8000`                                       |

## Out of scope (Phase 1)

Voice/Bhashini, crop recommendation, user accounts, market prices, multi-language.
