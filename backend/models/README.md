# Model file

Place your trained MobileNetV2 TFLite model here as:

```
paddy_disease_model.tflite
```

## Class order

The model output indices must match this order (index 0 → 5):

1. Leaf Blast
2. Bacterial Leaf Blight
3. Brown Spot
4. Tungro
5. Sheath Blight
6. Healthy

## Custom path

Set the `MODEL_PATH` environment variable to use a different file location.

## Input

- Size: 224×224 RGB (override with `MODEL_INPUT_SIZE`)
- Normalization: `(pixel / 127.5) - 1.0` (MobileNetV2 standard)
