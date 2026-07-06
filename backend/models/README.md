# Paddy Doctor — ResNet34 model

Place your trained **ResNet34** TFLite export here:

```
paddy_disease_model.tflite
```

Trained on the [Paddy Doctor dataset](https://paddydoc.github.io/) (16,225 images, 13 classes).  
Paper benchmark: ResNet34 achieved **97.50% F1-score** (best among DCNN, MobileNet, VGG16, Xception).

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

## Input preprocessing (ResNet34)

Matches Keras `resnet50.preprocess_input` used with ImageNet-pretrained ResNet fine-tuning:

- **Size:** 256×256 RGB (Paddy Doctor paper)
- **Steps:** RGB → BGR, then subtract channel means `[103.939, 116.779, 123.68]`

If your training used simple `rescale=1./255` instead, set:

```bash
export MODEL_PREPROCESS=scale
```

## Convert Keras model to TFLite

```bash
python scripts/convert_to_tflite.py path/to/resnet34_model.h5
```

## Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `MODEL_PATH` | `backend/models/paddy_disease_model.tflite` | Path to `.tflite` file |
| `MODEL_INPUT_SIZE` | `256` | Input width/height |
| `MODEL_PREPROCESS` | `resnet` | `resnet` or `scale` |
