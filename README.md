# Kisan Mitra — AI Crop Advisor for Paddy Farmers

A farmer takes a photo of a rice leaf. The app says **which disease it is**, **how sure it is**, and
**what to do about it**. The farmer can then ask follow-up questions by text or voice in Hindi, Marathi or English.

It runs as a web app and an Android app, both talking to one Python (FastAPI) server.

---

## Try it in 5 minutes (on your laptop + your phone)

You do **not** need AWS for this. You need Python 3.10+, and, to build the Android app, Node.js and Android Studio.

**Step 1. Install**
```
pip install -r requirements.txt
npm install
```

**Step 2. Build the app and start the server**
```
py kisan.py all
```
This builds a test APK (`dist/KisanMitra-test.apk`) and then starts the server. Leave this window open.

> On Windows you can type `kisan all` instead. Don't write `py kisan all` — `kisan` is a `.cmd` file, not a Python file.

**Step 3. Let your phone reach your laptop (once)**
```
py kisan.py firewall
```
It prints one command. Paste it into PowerShell opened **as Administrator**.

**Step 4. Install the app on your phone**
1. Connect the phone to the **same Wi-Fi** as the laptop.
2. Check it works: open `http://<laptop-ip>:8000/healthz` in the phone's browser (the server prints this address). You should see `{"status":"ok"}`.
3. Copy `dist/KisanMitra-test.apk` to the phone and install it (allow "install unknown apps").

**Step 5. Test**
- Photo of a **rice leaf** → you get a disease name and treatment.
- Photo of **anything else** → "This doesn't look like a rice leaf. Take a close, well-lit photo…"

If the laptop's IP address changes (new Wi-Fi), run `py kisan.py apk` again and reinstall the app.

---

## Test without a phone

With the server running (`py kisan.py serve` in another window):
```
py kisan.py diagnose data/train_images/blast     # rice photos  → [CLASSIFIED]
py kisan.py diagnose some/other/photos           # other photos → [REJECTED]
py kisan.py check                                # is everything loaded?
```
(`data/` is the Kaggle *Paddy Doctor* dataset, which is not in git. Use any rice photos you have.)

### All the CLI commands

| Command | What it does |
|---|---|
| `py kisan.py all` | Build the APK, then start the server |
| `py kisan.py serve` | Start the server only |
| `py kisan.py apk` | Build the APK only (re-run if your laptop's IP changes) |
| `py kisan.py diagnose <photo or folder>` | Send photos to the server and show the verdict |
| `py kisan.py check` | Is the server up? Are the model files there? |
| `py kisan.py firewall` | Print the Windows firewall command |
| `py kisan.py ip` | Show your laptop's Wi-Fi address |

Notes for this test setup:
- The server runs in **guest mode** (no login). Real login (SMS code) needs AWS.
- You will see AWS/DynamoDB errors in the server window. They are harmless here; the diagnosis still works.
- **Chat and voice** need an AI key in a `.env` file (copy `.env.example`). Photo diagnosis does not.

---

## How it works

```
photo → [1] Crop gate → [2] Disease model → [3] Confidence check → [4] Treatment → chat / voice
          │
          └─ not a rice leaf → rejected (HTTP 422), nothing is diagnosed
```

1. **Crop gate** — answers "is this a rice leaf?". Without it, a photo of a shoe would still be called "Brown Spot".
2. **Disease model** — picks one of 10 classes: Bacterial Leaf Blight, Bacterial Leaf Streak, Bacterial Panicle Blight,
   Blast, Brown Spot, Dead Heart, Downy Mildew, Hispa, Normal, Tungro.
3. **Confidence check** — a low-confidence answer is still shown, but with a warning. A shaky "Normal" never tells a farmer the crop is healthy.
4. **Treatment** — written by experts in `backend/diseases.json`. It never comes from the AI model.
5. **Chat / voice** — an AI assistant answers questions using only that same treatment file.

Both models live in `backend/models/`:

| File | What it is |
|---|---|
| `crop_gate.tflite` + `crop_gate.json` | The crop gate |
| `paddy_disease_model_fold0.tflite` + `model_meta.json` | The disease model |

### How accurate is it?

| Test | Result |
|---|---|
| Disease model on photos it never saw | 97.6% correct |
| Gate: 200 rice photos it never saw | 200 accepted |
| Gate: 960 photos of other plants and weeds | 959 rejected |
| Gate: blank, noise and screenshot images | all rejected |

These are photos from datasets. Real farmer photos (poor light, blur, hands, soil) will score lower — test with 100–200 real field photos before trusting it.

---

## Settings you might change

Copy `.env.example` to `.env`. You don't need to change anything to run the models.

| Setting | What it does |
|---|---|
| `LLM_PROVIDER` + its `..._API_KEY` | Which AI answers chat: `sambanova`, `gemini`, `openai`, `anthropic` or `huggingface` |
| `CROP_GATE=0` | Turn the gate off (every photo gets a disease) |
| `CROP_GATE_THRESHOLD` | How strict the gate is (default is in `crop_gate.json`) |
| `CONFIDENCE_THRESHOLD` | Below this a diagnosis gets a warning (default is in `model_meta.json`) |
| `BHASHINI_*`, `VOICE_STT_PROVIDER` | Voice (speech to text / text to speech) |

The full list is in `.env.example`.

---

## Retraining the models

Training is done in Google Colab (free GPU), then the result is copied into `backend/models/`.

| Notebook | Use it to |
|---|---|
| `Kisan_Mitra_Crop_and_NonCrop_Training.ipynb` | Train the **crop gate** (and optionally a disease model). Set `TRAIN_DISEASE` / `TRAIN_GATE` at the top. Needs a Kaggle token. |
| `Kisan_Mitra_Rice_Disease_Classifier_v3.ipynb` | Train the best **disease model** (5-model ensemble) |
| `Kisan_Mitra_Rice_Disease_Classifier_v2.ipynb` | Older model, kept for reference |

If the gate wrongly rejects real rice leaves, or accepts things it shouldn't, add example photos of those and retrain it.
More detail: `backend/models/README.md`.

---

## Deploying for real

- **Server on AWS:** see `DEPLOY.md`. Pushing to the `phase-1-mvp` branch runs `.github/workflows/deploy.yml`.
- **Play Store build:** see `MOBILE.md` (needs an HTTPS server).
- Other ways to run the server: `./start.sh`, or `docker-compose up --build`. API docs are at `http://localhost:8000/docs`.

---

## Something not working?

| Problem | Fix |
|---|---|
| Every photo gets a disease, nothing is rejected | Gate files are missing. Run `py kisan.py check`; both `crop_gate.tflite` and `crop_gate.json` must be in `backend/models/`. |
| Phone can't reach the laptop | Same Wi-Fi? Firewall command run as Administrator? Does `http://<laptop-ip>:8000/healthz` open on the phone? Did the IP change (re-run `py kisan.py apk`)? |
| A real rice leaf is rejected | Take a closer, well-lit photo that fills the frame. Or lower `CROP_GATE_THRESHOLD`, or retrain the gate with more photos like it. |
| `py kisan all` fails with a SyntaxError | Use `py kisan.py all` or `kisan all`. |
| Predictions look random | The disease model wasn't found (`model_mode` is `random`). Check `backend/models/`. |
| Colab export error `ERROR_NEEDS_FLEX_OPS` | Restart the Colab runtime and re-run the current notebook. |

---

## Where things are

```
backend/        the server (Python / FastAPI)
  models/         the two AI models
  diseases.json   expert treatment advice
web/            the farmer app (React) — also packed into the Android app
android/        Android wrapper
frontend/       staff dashboard and privacy pages
infra/          AWS setup (Terraform)
scripts/        training and testing helpers
kisan.py        the dev CLI used above
```

## License

Copyright © 2026 MRFOUNDERS (Mayur & Raj). All rights reserved.

This project and its source code are proprietary to MRFOUNDERS. No part of this
repository may be copied, modified, distributed, or used without prior written
permission from the copyright holders.
