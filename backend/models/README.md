# Models

Everything the backend needs is in this folder:

| File | Role |
|---|---|
| `crop_gate.tflite` + `crop_gate.json` | **Crop gate**: P(photo is a rice leaf). Photos below `threshold` get HTTP 422 and are never diagnosed. If these are missing the gate is off and every image gets a disease. |
| `paddy_disease_model_fold0.tflite` + `model_meta.json` | **Disease classifier** (10 classes) and its class order, temperature, input size and recommended confidence threshold |

Both are produced by `Kisan_Mitra_Crop_and_NonCrop_Training.ipynb` (or the v3 notebook for a 5-fold disease ensemble).
Check them with `py kisan.py check` from the project root.

## Disease models

The backend loads whatever is in this folder (`MODEL_PATH=backend/models`, the default):

- If `model_meta.json` exists, only the `.tflite` files it lists are loaded, as an ensemble.
  Class order, temperature and the recommended confidence threshold also come from it.
- Otherwise every `*.tflite` here is loaded.

Every prediction is averaged over all models and over the image plus its horizontal flip
(`MODEL_TTA=1`). The input size is read from each `.tflite` file.

## Getting the v3 models

1. Run `Kisan_Mitra_Rice_Disease_Classifier_v3.ipynb` (5-fold ensemble) or
   `Kisan_Mitra_Crop_and_NonCrop_Training.ipynb` (one model + the gate) on a Colab GPU.
2. Download the zip from the last cells and unzip it here, so you have the `.tflite` files and `model_meta.json`
   (plus `crop_gate.tflite` / `crop_gate.json` from the second notebook).
3. Restart the backend and check `GET /health`: `ensemble_size` is the number of models listed in
   `model_meta.json` and `model_arch` the backbone you trained.

Other `.tflite` files here are ignored when `model_meta.json` exists (the crop gate is loaded separately).

## Class order (index 0 → 9)

Alphabetical folder order from the dataset. Names must match `backend/diseases.json`.

| Index | Class |
|-------|-------|
| 0 | Bacterial Leaf Blight |
| 1 | Bacterial Leaf Streak |
| 2 | Bacterial Panicle Blight |
| 3 | Blast |
| 4 | Brown Spot |
| 5 | Dead Heart |
| 6 | Downy Mildew |
| 7 | Hispa |
| 8 | Normal |
| 9 | Tungro |

## Input preprocessing

Both notebooks put the preprocessing inside the model, so the backend sends raw 0–255 RGB pixels
(`MODEL_PREPROCESS=none`). Before resizing, the backend applies the photo's EXIF rotation and turns
landscape photos to portrait. The v3 notebook trains with exactly the same steps.

## Crop gate settings

`crop_gate.json` holds the `threshold` chosen at training time (it keeps ~98% of rice photos) plus its validation
metrics. `CROP_GATE=0` turns the gate off; `CROP_GATE_THRESHOLD` overrides the cut-off.

## Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `MODEL_PATH` | `backend/models` | Folder of models, or a single `.tflite` file |
| `MODEL_PREPROCESS` | `none` | `none`, `mobilenet`, `resnet`, or `scale` |
| `MODEL_TTA` | `1` | Average over the image and its horizontal flip |
| `MODEL_NUM_THREADS` | CPU count | TFLite interpreter threads |
| `MODEL_INPUT_SIZE` | `224` | Only used if a model has a dynamic input shape |
| `CONFIDENCE_THRESHOLD` | from `model_meta.json`, else `60` | Below this, results are marked uncertain |
