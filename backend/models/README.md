# Paddy Doctor — MobileNetV2 model

Place your trained **MobileNetV2** TFLite export here:

```
paddy_disease_model.tflite
```

Trained on the [Kaggle "Paddy Doctor: Paddy Disease Classification"](https://www.kaggle.com/competitions/paddy-disease-classification) competition dataset (~10,400 training images, 10 classes: 9 diseases + normal). This is what `Kisan_Mitra_Rice_Disease_Classifier_v2.ipynb` trains — run it, then convert the saved Keras model with `scripts/convert_to_tflite.py`.

## Class order (index 0 → 9)

Must match training label order:

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

`tf.keras.utils.image_dataset_from_directory` (used in the training notebook) sorts folder names alphabetically (`bacterial_leaf_blight`, `bacterial_leaf_streak`, `bacterial_panicle_blight`, `blast`, `brown_spot`, `dead_heart`, `downy_mildew`, `hispa`, `normal`, `tungro`), which matches this order.

## Input preprocessing — important

The training notebook applies `mobilenet_v2.preprocess_input` **as a layer inside
the Keras model itself** (`x = preprocess_input(x)` runs on `inputs` before
`base_model`, inside the functional model definition). That means the
[-1, 1] rescaling gets traced into the exported `.tflite` graph automatically —
the model expects **raw 0-255 pixel values** as input, not pre-scaled ones.

- **Size:** 224×224 RGB
- **`MODEL_PREPROCESS=none`** (default) — pass raw pixels through unchanged. Use this.

Feeding manually-rescaled pixels here double-applies the scaling and silently
skews every prediction (same file, same model, different — wrong — results).
Only switch away from `none` if you retrain with preprocessing done *outside*
the model graph:

```bash
export MODEL_PREPROCESS=mobilenet  # scale to [-1, 1] — only if NOT already baked into the model
export MODEL_PREPROCESS=resnet     # ImageNet ResNet caffe-mode (BGR + mean subtraction)
export MODEL_PREPROCESS=scale      # simple rescale=1./255
```

## Convert Keras model to TFLite

```bash
python scripts/convert_to_tflite.py path/to/rice_disease_model.keras
```

## Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `MODEL_PATH` | `backend/models/paddy_disease_model.tflite` | Path to `.tflite` file |
| `MODEL_INPUT_SIZE` | `224` | Input width/height |
| `MODEL_PREPROCESS` | `none` | `none`, `mobilenet`, `resnet`, or `scale` |
