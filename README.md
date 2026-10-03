# Kisan Mitra — AI Crop Advisor for Paddy Farmers

A farmer photographs a rice leaf and gets the disease name, how sure the model is, and treatment
advice. They can then ask follow-up questions by text or voice in Hindi, Marathi or English.
It ships as a web app and an Android app (Capacitor) backed by one FastAPI server.

## How it works

```
 phone photo ──▶ Crop gate ──▶ Disease classifier ──▶ Treatment (diseases.json) ──▶ Chat / Voice
                  │                  │
                  │ "is this a       │ 10 classes, 97.6% accuracy on held-out
                  │  rice leaf?"     │ Paddy Doctor photos (EfficientNetV2-S)
                  ▼
            not a leaf → HTTP 422 "This doesn't look like a rice leaf. Take a close,
                         well-lit photo of a single rice leaf and try again."
```

1. **Crop gate** (`backend/models/crop_gate.tflite`). A small MobileNetV2 + logistic head that answers
   "is this a rice leaf photo?". The disease model only knows 10 rice classes, so without the gate a
   photo of a shoe still gets labelled "Brown Spot". Photos below the gate threshold are rejected and
   nothing is diagnosed or stored.
2. **Disease classifier** (`backend/models/paddy_disease_model_fold0.tflite`). EfficientNetV2-S trained on
   the Kaggle *Paddy Doctor* dataset. Each prediction averages the image and its horizontal flip, then applies
   temperature scaling so the confidence is calibrated.
3. **Confidence check.** Below the recommended threshold the result is still shown but marked
   `safe_to_act: false` with a warning; the app must keep that warning visible. A low-confidence "Normal"
   never tells a farmer the crop is healthy.
4. **Treatment.** Cause, severity, organic and chemical treatment come from the vetted knowledge base
   `backend/diseases.json`, not from the model or an LLM.
5. **Chat and voice.** An LLM answers questions grounded in that same knowledge base, optionally about
   the diagnosis just made. Voice uses speech-to-text and text-to-speech around the same chat.

The 10 classes: Bacterial Leaf Blight, Bacterial Leaf Streak, Bacterial Panicle Blight, Blast, Brown Spot,
Dead Heart, Downy Mildew, Hispa, Normal, Tungro.

### How good is it?

| Check | Result |
|---|---|
| Disease model, held-out Paddy Doctor photos | 97.6% accuracy (`oof_accuracy` in `model_meta.json`) |
| Crop gate, rice photos it never trained on (200) | 200/200 accepted |
| Crop gate, other plants/weeds never trained on (960, Kaggle *Plant Seedlings*) | 959/960 rejected |
| Crop gate, blank / noise / flat-colour / screenshot images | all rejected |

These are photos from datasets. Real farmer photos (bad light, blur, hands, soil) will score lower, so
test on 100–200 labelled field photos before trusting it. The gate is tested against other plants but not
yet against hands, soil or rice grain.

## Quickstart: run it and test on your phone (no AWS needed)

Requirements: Python 3.10+, and for the Android app Node.js 18+, JDK 17–21 and the Android SDK
(Android Studio installs both).

```bash
pip install -r requirements.txt
npm install                        # only needed to build the app

py kisan.py all                    # build the debug APK, then start the backend
```

`kisan.py` is a dev CLI (standard library only; on Windows `kisan` also works):

| Command | What it does |
|---|---|
| `py kisan.py serve` | Start the backend in guest mode (no login), reachable from your phone at `http://<laptop-ip>:8000` |
| `py kisan.py apk` | Point the app at this laptop's IP and build `dist/KisanMitra-test.apk` |
| `py kisan.py all` | `apk`, then `serve` |
| `py kisan.py check` | Is the backend up, are all four model files present, is `model_mode` `tflite`? |
| `py kisan.py diagnose <photo or folder>` | Send photos through the real gate + classifier; prints `[CLASSIFIED]` or `[REJECTED]` |
| `py kisan.py ip` / `firewall` | Show the laptop's LAN IP / print the Windows firewall command |

To use the app on a phone:
1. Run `py kisan.py firewall` and run the command it prints in an **Administrator** PowerShell (once).
   Windows blocks incoming connections on "Public" Wi-Fi.
2. Keep the laptop and the phone on the **same Wi-Fi**. Check `http://<laptop-ip>:8000/healthz` in the phone's browser.
3. Copy `dist/KisanMitra-test.apk` to the phone and install it (allow "install unknown apps").
4. Keep the terminal running `serve`. Photos of rice leaves are classified; anything else is rejected.

The IP is baked into the APK, so run `py kisan.py apk` again whenever the laptop's IP changes.
In guest mode the server still tries to log to DynamoDB; those errors in the log are harmless, and
`/diagnose` returns its result anyway. Chat needs an LLM key in `.env` (see Configuration).

Quick model check without a phone:
```bash
py kisan.py diagnose data/train_images/blast       # should classify as Blast
py kisan.py diagnose path/to/random/photos         # should be rejected
```

### Other ways to run the backend
```bash
./start.sh                                   # installs deps and starts the server
cd backend && uvicorn main:app --port 8000   # manual
docker-compose up --build -d                 # Docker; mounts ./backend/models read-only
```
The web app is served at `http://localhost:8000` once built (`npm run build` creates `web/dist`).
API docs are at `/docs`.

## Configuration

Copy `.env.example` to `.env`. Nothing is required to run the models locally. Common settings:

| Variable | Default | Purpose |
|---|---|---|
| `AUTH_DISABLED` | off | `1` = guest mode, no login (the CLI sets this for you; build the app with `VITE_AUTH_DISABLED=1`) |
| `MODEL_PATH` | `backend/models` | Folder with the models (or one `.tflite`) |
| `CROP_GATE` | `1` | `0` turns the gate off (every image is diagnosed) |
| `CROP_GATE_THRESHOLD` | from `crop_gate.json` | Override the gate's cut-off |
| `CONFIDENCE_THRESHOLD` | from `model_meta.json` | Below this a diagnosis is marked uncertain |
| `MODEL_TTA` | `1` | Average over the image and its mirror image |
| `MAX_IMAGE_SIZE_MB` | `10` | Upload limit |
| `LLM_PROVIDER` | `sambanova` | Chat model: `sambanova`, `gemini`, `openai`, `anthropic`, `huggingface` |
| `LLM_FALLBACK_PROVIDERS` | | Providers to try, in order, if the first fails |
| `<PROVIDER>_API_KEY` | | `SAMBANOVA_`, `GEMINI_`, `OPENAI_`, `ANTHROPIC_`, `HUGGINGFACE_` |
| `VOICE_STT_PROVIDER` | `mlx` | Speech-to-text: `mlx` (Apple Silicon, local), `bhashini` (cloud), `auto` |
| `BHASHINI_USER_ID`, `BHASHINI_API_KEY`, `BHASHINI_PIPELINE_ID` | | Bhashini voice (also TTS) |
| `RATE_LIMIT_PER_MINUTE` / `RATE_LIMIT_PER_DAY` | `10` / `200` | Per-farmer limits |
| `CORS_ORIGINS` | `*` | Restrict in production, e.g. `https://localhost` |
| `AWS_*`, `COGNITO_*`, `DYNAMODB_TABLE_PREFIX` | | Real login (SMS OTP) and data storage; created by `infra/` |

See `backend/models/README.md` for the model-related settings in detail.

## API

Interactive docs at `/docs`. Main endpoints:

| Method | Path | Description |
|---|---|---|
| `POST` | `/diagnose` | Photo → gate → disease, confidence, treatment. `422` if it isn't a rice leaf |
| `POST` | `/diagnose/feedback` | Mark a diagnosis helpful / not helpful |
| `GET` | `/diseases` | The full treatment knowledge base |
| `POST` | `/chat` | Text chat, optionally with a diagnosis as context |
| `GET` | `/voice/status` | Which speech providers are available |
| `POST` | `/voice/stt`, `/voice/tts`, `/voice/chat` | Speech → text, text → speech, whole voice round trip |
| `POST` | `/auth/otp/start`, `/auth/otp/verify`, `/auth/refresh`, `/auth/logout` | Farmer login by SMS code |
| `GET`/`PATCH`/`DELETE` | `/auth/me` | Profile; delete my account and data |
| `POST` | `/admin/auth/login`, `/admin/auth/challenge`, `/admin/auth/refresh`, `/admin/auth/logout` | Staff login (password + MFA) |
| `GET` | `/dashboard`, `/dashboard/stats`, `/dashboard/recent` | Field-team dashboard (staff only) |
| `GET` | `/health`, `/healthz` | Full status / cheap liveness check |

## Project structure

```
backend/
  main.py, schemas.py
  inference.py             TFLite disease model + crop gate
  chat_service.py          LLM chat grounded in diseases.json (multi-provider with fallback)
  voice_service.py, bhashini_service.py, mlx_stt_service.py
  auth_service.py          Cognito login / token checks
  database.py              DynamoDB (users, diagnoses, stats, rate limits)
  ratelimit.py             per-farmer limits
  diseases.json            vetted treatment knowledge base
  routers/                 health, diseases, diagnose, chat, voice, auth, dashboard
  models/                  crop_gate.tflite/.json, paddy_disease_model_fold0.tflite, model_meta.json
web/                       the farmer app (React + Vite, i18n: Hindi / Marathi / English)
frontend/                  staff dashboard and legal pages
android/, capacitor.config.ts   Android wrapper around web/
infra/                     Terraform for AWS (ECS Fargate, DynamoDB, Cognito, WAF, ...)
scripts/                   training / evaluation helpers (below)
kisan.py                   dev CLI
```

## Training the models

Both models are trained in Google Colab on a GPU and exported to TFLite; copy the output into `backend/models/`.

| Notebook | Trains |
|---|---|
| `Kisan_Mitra_Crop_and_NonCrop_Training.ipynb` | **Crop gate** (rice vs everything else) and optionally a single disease model. Set `TRAIN_DISEASE`, `TRAIN_GATE` at the top. Needs a Kaggle token. |
| `Kisan_Mitra_Rice_Disease_Classifier_v3.ipynb` | Best disease model: 5-fold EfficientNetV2-S ensemble, pseudo-labelling, calibrated confidence threshold |
| `Kisan_Mitra_Rice_Disease_Classifier_v2.ipynb` | Original MobileNetV2 model (kept for reference) |

The gate is trained on rice photos (positives) against textures, objects, animals and other crops' leaves
(negatives), plus any photos of your own in a Drive folder. Add the wrong photos farmers actually take.

Scripts: `train_crop_gate.py` (train the gate locally), `download_negatives.py` (fetch non-rice images),
`eval_classifier.py` (measure the gate + classifier on a folder), `convert_to_tflite.py` (Keras → TFLite).

## Deploying

- **AWS (production):** see `DEPLOY.md` (Terraform in `infra/`, GitHub Actions in `.github/workflows/`).
- **Android release build and Play Store:** see `MOBILE.md`. Release builds require an HTTPS backend.

## Troubleshooting

- **Every photo gets a disease:** the gate files are missing. `py kisan.py check` shows which; both
  `crop_gate.tflite` and `crop_gate.json` must be in `backend/models/`. The server log says "Crop gate inactive".
- **`model_mode` is `random`:** no model was found at `MODEL_PATH`, so predictions are random. Fix the path.
- **Phone can't reach the laptop:** same Wi-Fi? Firewall rule added? Does `http://<laptop-ip>:8000/healthz` open on the phone?
  Did the laptop's IP change (rebuild with `py kisan.py apk`)?
- **A real rice leaf is rejected:** take a closer, well-lit photo that fills the frame. To loosen the gate set
  `CROP_GATE_THRESHOLD` lower; to retrain it, add such photos and use the notebook above.
- **DynamoDB / AWS errors in the log while testing locally:** expected without AWS. Diagnosis still works.
- **Notebook export fails with `ERROR_NEEDS_FLEX_OPS`:** the notebook was exporting under mixed precision. Use the
  current notebook, or restart the Colab runtime before running it.

## License

Copyright © 2026 MRFOUNDERS (Mayur & Raj). All rights reserved.

This project and its source code are proprietary to MRFOUNDERS. No part of this
repository may be copied, modified, distributed, or used without prior written
permission from the copyright holders.
