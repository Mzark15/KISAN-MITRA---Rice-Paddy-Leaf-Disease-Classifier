#!/usr/bin/env python3
"""Convert a trained Keras model (.h5 / .keras) to TFLite for Kisan Mitra."""

import argparse
import os
import sys


def convert(model_path: str, output_path: str) -> None:
    try:
        import tensorflow as tf
    except ImportError as exc:
        print("TensorFlow required: pip install tensorflow", file=sys.stderr)
        raise SystemExit(1) from exc

    print(f"Loading {model_path}...")
    model = tf.keras.models.load_model(model_path)

    converter = tf.lite.TFLiteConverter.from_keras_model(model)
    converter.optimizations = [tf.lite.Optimize.DEFAULT]
    tflite_model = converter.convert()

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    with open(output_path, "wb") as f:
        f.write(tflite_model)

    print(f"Saved TFLite model to {output_path}")
    print(f"Output classes: {model.output_shape[-1]} (expect 13 for Paddy Doctor)")


def main() -> None:
    default_out = os.path.join(
        os.path.dirname(__file__), "..", "backend", "models", "paddy_disease_model.tflite"
    )
    parser = argparse.ArgumentParser(description="Convert Keras model to TFLite")
    parser.add_argument("model", help="Path to .h5 or .keras model file")
    parser.add_argument("-o", "--output", default=default_out, help="Output .tflite path")
    args = parser.parse_args()
    convert(args.model, os.path.abspath(args.output))


if __name__ == "__main__":
    main()
