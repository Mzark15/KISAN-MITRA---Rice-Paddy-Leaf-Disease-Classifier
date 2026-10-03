"""Train the "is this a rice leaf photo?" gate and export it as backend/models/crop_gate.tflite.

The disease classifier only knows 10 rice classes, so it will happily label a photo of a
shoe as "Brown Spot". This gate sits in front of it: MobileNetV2 (ImageNet) features plus a
logistic-regression head that outputs P(rice leaf). The backend rejects anything below the
threshold written to backend/models/crop_gate.json.

Positives: Paddy Doctor photos in data/train_images/<class>/*.jpg
Negatives: every image folder under data/not_crop/ (torchvision downloads land in
           data/not_crop/_raw, see download_negatives.py) + synthetic blank/noise frames.

    py scripts/train_crop_gate.py
"""

import json
import os
import random
import sys

import numpy as np
from PIL import Image, ImageOps
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score, roc_curve
from sklearn.model_selection import train_test_split

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
POS_DIR = os.path.join(ROOT, "data", "train_images")
NEG_DIR = os.path.join(ROOT, "data", "not_crop")
OUT_DIR = os.path.join(ROOT, "backend", "models")
SIZE = 224
POS_PER_CLASS = int(os.environ.get("POS_PER_CLASS", "250"))
NEG_MAX = int(os.environ.get("NEG_MAX", "6000"))
TARGET_RECALL = 0.98  # share of real rice-leaf photos the gate must let through

random.seed(0)
np.random.seed(0)

IMG_EXT = (".jpg", ".jpeg", ".png", ".bmp", ".webp")


def list_images(folder: str) -> list[str]:
    out = []
    for dirpath, _, files in os.walk(folder):
        out += [os.path.join(dirpath, f) for f in files if f.lower().endswith(IMG_EXT)]
    return out


def prepare(img: Image.Image) -> Image.Image:
    """Same orientation handling as backend/inference.py:prepare_image."""
    img = ImageOps.exif_transpose(img).convert("RGB")
    if img.width > img.height:
        img = img.rotate(90, expand=True)
    return img


def views(img: Image.Image, n: int = 2) -> list[np.ndarray]:
    """Full frame plus randomly zoomed/flipped crops — farmers shoot both wide and close."""
    img = prepare(img)
    out = [np.asarray(img.resize((SIZE, SIZE), Image.Resampling.BILINEAR), dtype=np.float32)]
    for _ in range(n - 1):
        scale = random.uniform(0.55, 1.0)
        w, h = int(img.width * scale), int(img.height * scale)
        x, y = random.randint(0, img.width - w), random.randint(0, img.height - h)
        crop = img.crop((x, y, x + w, y + h))
        if random.random() < 0.5:
            crop = ImageOps.mirror(crop)
        out.append(np.asarray(crop.resize((SIZE, SIZE), Image.Resampling.BILINEAR), dtype=np.float32))
    return out


def synthetic_negatives(n: int) -> list[np.ndarray]:
    """Blank, dark, noisy and gradient frames — what a covered lens or a wall looks like."""
    out = []
    for i in range(n):
        kind = i % 4
        if kind == 0:  # flat colour
            arr = np.ones((SIZE, SIZE, 3), np.float32) * np.random.randint(0, 256, 3)
        elif kind == 1:  # very dark
            arr = np.random.rand(SIZE, SIZE, 3).astype(np.float32) * 40
        elif kind == 2:  # noise
            arr = np.random.rand(SIZE, SIZE, 3).astype(np.float32) * 255
        else:  # gradient
            a, b = np.random.randint(0, 256, 3), np.random.randint(0, 256, 3)
            t = np.linspace(0, 1, SIZE, dtype=np.float32)[:, None, None]
            arr = a * (1 - t) + b * t
            arr = np.broadcast_to(arr, (SIZE, SIZE, 3)).copy()
        out.append(arr.astype(np.float32))
    return out


def build_extractor():
    import tensorflow as tf

    inp = tf.keras.Input((SIZE, SIZE, 3), name="image")  # raw 0-255 RGB
    x = tf.keras.layers.Rescaling(1 / 127.5, offset=-1)(inp)
    base = tf.keras.applications.MobileNetV2(
        input_shape=(SIZE, SIZE, 3), include_top=False, weights="imagenet", pooling="avg"
    )
    feats = base(x)
    return tf.keras.Model(inp, feats), tf


def embed(extractor, arrays: list[np.ndarray]) -> np.ndarray:
    out = []
    for i in range(0, len(arrays), 64):
        out.append(extractor.predict(np.stack(arrays[i : i + 64]), verbose=0))
    return np.concatenate(out)


def main() -> None:
    pos_files = []
    for cls in sorted(os.listdir(POS_DIR)):
        files = list_images(os.path.join(POS_DIR, cls))
        random.shuffle(files)
        pos_files += files[:POS_PER_CLASS]
    neg_files = list_images(NEG_DIR)
    random.shuffle(neg_files)
    neg_files = neg_files[:NEG_MAX]
    if len(neg_files) < 200:
        sys.exit(f"Only {len(neg_files)} negative images under {NEG_DIR}; download more first.")
    print(f"positives: {len(pos_files)} files, negatives: {len(neg_files)} files")

    extractor, tf = build_extractor()

    # Split by source file so crops of one photo never land on both sides of the split.
    pos_tr, pos_va = train_test_split(pos_files, test_size=0.2, random_state=0)
    neg_tr, neg_va = train_test_split(neg_files, test_size=0.2, random_state=0)

    def load(files, label, n_views):
        arrays, labels = [], []
        for f in files:
            try:
                with Image.open(f) as im:
                    v = views(im, n_views)
            except Exception:
                continue
            arrays += v
            labels += [label] * len(v)
        return arrays, labels

    sets = {}
    for name, (pf, nf, nv) in {"train": (pos_tr, neg_tr, 2), "val": (pos_va, neg_va, 2)}.items():
        pa, pl = load(pf, 1, nv)
        na, nl = load(nf, 0, nv)
        sa = synthetic_negatives(max(40, len(na) // 25))
        arrays = pa + na + sa
        labels = pl + nl + [0] * len(sa)
        print(f"{name}: embedding {len(arrays)} images")
        sets[name] = (embed(extractor, arrays), np.array(labels))

    (Xtr, ytr), (Xva, yva) = sets["train"], sets["val"]
    clf = LogisticRegression(C=0.5, max_iter=2000, class_weight="balanced")
    clf.fit(Xtr, ytr)
    p = clf.predict_proba(Xva)[:, 1]
    auc = roc_auc_score(yva, p)
    fpr, tpr, thr = roc_curve(yva, p)
    ok = np.where(tpr >= TARGET_RECALL)[0][0]
    threshold = float(thr[ok])
    print(f"val AUC {auc:.4f}; threshold {threshold:.3f} keeps {tpr[ok]:.1%} of rice photos "
          f"and lets through {fpr[ok]:.1%} of non-rice images")

    # Bake the logistic head into the graph so the .tflite outputs P(rice leaf) directly.
    head = tf.keras.layers.Dense(1, activation="sigmoid", name="rice_leaf")
    model = tf.keras.Sequential([extractor, head])
    model.build((None, SIZE, SIZE, 3))
    head.set_weights([clf.coef_.T.astype(np.float32), clf.intercept_.astype(np.float32)])

    # Sanity check: the baked-in head must agree with sklearn.
    probe = np.random.rand(1, SIZE, SIZE, 3).astype(np.float32) * 255
    assert abs(float(model.predict(probe, verbose=0)[0, 0]) - float(clf.predict_proba(embed(extractor, list(probe)))[0, 1])) < 1e-3

    conv = tf.lite.TFLiteConverter.from_keras_model(model)
    conv.optimizations = [tf.lite.Optimize.DEFAULT]
    tflite_bytes = conv.convert()
    os.makedirs(OUT_DIR, exist_ok=True)
    with open(os.path.join(OUT_DIR, "crop_gate.tflite"), "wb") as f:
        f.write(tflite_bytes)
    with open(os.path.join(OUT_DIR, "crop_gate.json"), "w", encoding="utf-8") as f:
        json.dump({"threshold": round(threshold, 4), "val_auc": round(float(auc), 4),
                   "rice_recall": round(float(tpr[ok]), 4), "non_rice_pass_rate": round(float(fpr[ok]), 4),
                   "input_size": SIZE}, f, indent=2)
    print(f"wrote crop_gate.tflite ({len(tflite_bytes) / 1e6:.1f} MB) and crop_gate.json")


if __name__ == "__main__":
    main()
