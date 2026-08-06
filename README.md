# Kisan Mitra — AI Crop Advisor (Paddy)

A multi-phase AI-powered application for paddy farmers, starting with disease detection, then adding chat, voice, and dashboard features.

## Features

### Phase 1 – Disease Detection
- Upload or capture a leaf photo
- Run inference using a TFLite model (MobileNetV2 trained on the Kaggle Paddy Doctor competition dataset)
- Get a diagnosis with confidence score
- View cause, severity, and organic/chemical treatment options
- No external cloud required for inference (works offline if model is present)
- 10-class classification (Bacterial Leaf Blight, Bacterial Leaf Streak, Bacterial Panicle Blight, Blast, Brown Spot, Dead Heart, Downy Mildew, Hispa, Normal, Tungro)

### Phase 2 – Chat
- Text chat in Hindi, Marathi, English
- LLM grounded in disease knowledge base (no hallucinations)
- Integrates SambaNova (default), OpenAI, Anthropic, or Gemini
- Optional diagnosis context (chat about a recent diagnosis)

### Phase 3 – Voice
- Speech-to-text (STT): local MLX (Apple Silicon) or Bhashini (cloud)
- Text-to-speech (TTS): Bhashini or browser fallback
- Voice chat flow: speak, get transcript, get AI reply, hear it back

### Phase 4 – Dashboard
- Field team dashboard with login
- Summary stats: total diagnoses, chats, voice sessions
- Charts: top diseases, last 7 days trend
- Recent diagnoses table with village and feedback
- Feedback: farmers can mark diagnoses helpful/not helpful
- Async SQLite persistence

## Quickstart (Local)

### 1. Prerequisites
- Python 3.10+
- For MLX STT (optional, Apple Silicon only):
  - macOS 13+
  - ffmpeg (`brew install ffmpeg`)

### 2. Install
```bash
git clone https://github.com/Mzark15/KISAN-MITRA---Rice-Paddy-Leaf-Disease-Classifier
cd krishi
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
# Optional: MLX STT for Apple Silicon
pip install -r requirements-mlx.txt
```

### 3. Configure
Copy `.env.example` to `.env` and set the variables you need:
```bash
cp .env.example .env
```

Minimal config for Phase 1 (no API keys needed):
```env
MODEL_PATH=backend/models/paddy_disease_model.tflite
MODEL_INPUT_SIZE=224
MODEL_PREPROCESS=none
DB_PATH=data/kisan_mitra.db
```

Add LLM provider for chat (choose one):
```env
LLM_PROVIDER=sambanova
SAMBANOVA_API_KEY=sk-...
# OR
LLM_PROVIDER=openai
OPENAI_API_KEY=sk-...
# OR
LLM_PROVIDER=gemini
GEMINI_API_KEY=...
# OR
LLM_PROVIDER=anthropic
ANTHROPIC_API_KEY=sk-...
```

Add Bhashini for voice (optional):
```env
VOICE_STT_PROVIDER=auto  # mlx first, then bhashini
BHASHINI_USER_ID=your-user-id
BHASHINI_API_KEY=your-api-key
BHASHINI_PIPELINE_ID=your-pipeline-id
```

### 4. Add Model
Download or place your TFLite model at `backend/models/paddy_disease_model.tflite`.
If no model is present, the app falls back to a random classification for testing.

### 5. Run
```bash
# Option A: Use start script
./start.sh

# Option B: Run manually
cd backend
python main.py
```

Open http://localhost:8000 in your browser.

## Docker

### Build & Run
```bash
docker-compose up --build -d
```

The app is served on http://localhost:8000.
Model directory is mounted from `./backend/models`, database from `./data`.

## Project Structure
```
krishi/
├── backend/
│   ├── main.py                 # FastAPI entrypoint
│   ├── inference.py            # TFLite model wrapper
│   ├── chat_service.py         # LLM chat with grounding
│   ├── voice_service.py        # STT/TTS router
│   ├── bhashini_service.py     # Bhashini ULCA API client
│   ├── mlx_stt_service.py      # Local MLX Qwen2-Audio STT
│   ├── database.py             # Async SQLite persistence
│   ├── schemas.py              # Pydantic models
│   ├── diseases.json           # Disease knowledge base
│   ├── routers/
│   │   ├── health.py           # Health and model info
│   │   ├── diseases.py         # Get static disease info
│   │   ├── diagnose.py         # Upload image → diagnosis
│   │   ├── chat.py             # Text chat endpoint
│   │   ├── voice.py            # Voice endpoints
│   │   └── dashboard.py        # Stats, recent, feedback
│   └── models/                 # TFLite model directory
├── frontend/
│   ├── index.html              # Farmer app
│   └── dashboard.html          # Field team dashboard
├── scripts/
│   └── convert_to_tflite.py    # Convert Keras model to TFLite
├── requirements.txt
├── requirements-mlx.txt        # Optional MLX dependencies
├── .env.example
├── .gitignore
├── Dockerfile
├── docker-compose.yml
└── start.sh
```

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/` | Serve app frontend |
| `GET` | `/health` | Health check & model info |
| `GET` | `/diseases` | Get full disease knowledge base |
| `POST` | `/diagnose` | Upload image → diagnosis |
| `POST` | `/diagnose/feedback` | Submit feedback on diagnosis |
| `POST` | `/chat` | Text chat with optional diagnosis context |
| `GET` | `/voice/status` | Check voice STT/TTS availability |
| `POST` | `/voice/stt` | Audio → text |
| `POST` | `/voice/tts` | Text → audio |
| `POST` | `/voice/chat` | Voice chat end‑to‑end |
| `GET` | `/dashboard` | Serve dashboard frontend |
| `GET` | `/dashboard/stats` | Get dashboard statistics |
| `GET` | `/dashboard/recent` | Get recent diagnoses |

## Environment Variables

| Name | Default | Description |
|------|---------|-------------|
| `PORT` | `8000` | Server port |
| `MODEL_PATH` | `backend/models/paddy_disease_model.tflite` | Path to TFLite model file |
| `MODEL_INPUT_SIZE` | `224` | Model input resolution (px) |
| `MODEL_PREPROCESS` | `none` | Preprocessing mode: `none` (preprocessing baked into the model graph — correct for the training notebook), `mobilenet` (scale to [-1,1]), `resnet` (ImageNet mean subtraction, BGR), or `scale` |
| `DB_PATH` | `data/kisan_mitra.db` | SQLite database path |
| `LLM_PROVIDER` | `sambanova` | LLM provider: `sambanova`, `openai`, `gemini`, `anthropic` |
| `SAMBANOVA_API_KEY` | | SambaNova API key |
| `SAMBANOVA_BASE_URL` | `https://api.sambanova.ai/v1` | SambaNova base URL |
| `SAMBANOVA_MODEL` | `Meta-Llama-3.3-70B-Instruct` | SambaNova model |
| `OPENAI_API_KEY` | | OpenAI API key |
| `GEMINI_API_KEY` | | Google AI Studio API key |
| `ANTHROPIC_API_KEY` | | Anthropic API key |
| `VOICE_STT_PROVIDER` | `mlx` | STT provider: `mlx`, `bhashini`, `auto` |
| `MLX_STT_ENABLED` | `1` | Enable/disable MLX STT |
| `MLX_STT_MODEL` | `mlx-community/Qwen2-Audio-7B-Instruct-4bit` | MLX model ID |
| `BHASHINI_USER_ID` | | Bhashini user ID |
| `BHASHINI_API_KEY` | | Bhashini API key |
| `BHASHINI_PIPELINE_ID` | | Bhashini pipeline ID (optional) |
| `DASHBOARD_PASSWORD` | `kisan123` | Dashboard login password |

## Model Integration

The app expects a TFLite model trained on the Kaggle Paddy Doctor competition dataset (10 classes, alphabetical order) — see `Kisan_Mitra_Rice_Disease_Classifier_v2.ipynb` and `backend/models/README.md`.

Use `scripts/convert_to_tflite.py` to convert a Keras model to TFLite:
```bash
cd scripts
python convert_to_tflite.py --model ../my_model.keras --output ../backend/models/paddy_disease_model.tflite
```

## Languages Supported

- **Diagnosis/disease reference**: English (UI in Hindi/Marathi/English)
- **Chat/voice**: Hindi, Marathi, English
- **Bhashini TTS/STT**: + Tamil, Telugu, Kannada, Punjabi, Gujarati, Bengali, Malayalam

## Troubleshooting

- **Model not loaded**: Check `MODEL_PATH` and ensure the file exists. If not, the app uses random predictions for testing.
- **MLX STT not working**: Ensure you’re on Apple Silicon, installed `requirements-mlx.txt`, installed ffmpeg, and `MLX_STT_ENABLED=1`.
- **CORS**: The app allows all origins in dev; adjust middleware in `main.py` for production.
- **Database**: The app creates the DB file and tables automatically if they don’t exist.

## License

Copyright © 2026 MRFOUNDERS (Mayur & Raj). All rights reserved.

This project and its source code are proprietary to MRFOUNDERS. No part of this
repository may be copied, modified, distributed, or used without prior written
permission from the copyright holders.
