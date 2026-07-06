# Paddy Doctor model

Place your trained **MobileNet** TFLite export here:

```
paddy_disease_model.tflite
```

Trained on the [Paddy Doctor dataset](https://paddydoc.github.io/) (16,225 images, 13 classes).

## Class order (index 0 → 12)

Must match training label order:

| Index | Class |
|-------|-------|
| 0 | Bacterial Leaf Blight |
| 1 | Bacterial Leaf Streak |
| 2 | Bacterial Panicle Blight |
| 3 | Black Stem Borer |
| 4 | Blast |
| 5 | Brown Spot |
| 6 | Downy Mildew |
| 7 | Hispa |
| 8 | Leaf Roller |
| 9 | Tungro |
| 10 | White Stem Borer |
| 11 | Yellow Stem Borer |
| 12 | Normal |

If you used Keras `ImageDataGenerator.flow_from_directory`, folder names are typically alphabetical (`bacterial_leaf_blight`, `blast`, …, `normal`) which matches this order.

## Input preprocessing

- **Size:** 256×256 RGB (Paddy Doctor paper benchmark)
- **Normalization:** `(pixel / 127.5) - 1.0` (Keras MobileNet `preprocess_input`)

Override size with `MODEL_INPUT_SIZE` if your export differs.

## Convert Keras model to TFLite

If you have a `.h5` or SavedModel instead of `.tflite`:

```bash
python scripts/convert_to_tflite.py path/to/your_model.h5
```

## Custom path

```bash
export MODEL_PATH=/path/to/your_model.tflite
```
