"""Measure the real backend path (crop gate -> disease model) on rice and non-rice photos.

Rice photos come from data/train_images, non-rice from data/not_crop. Some of these images
were seen by the gate during training, so treat the numbers as an optimistic smoke test; the
honest held-out figures are the validation numbers printed by train_crop_gate.py. For a real
check, run it on your own phone photos (drop them in a folder and extend `groups`). Reports,
per source:

  rice photos accepted by the gate          (want ~98%+)
  non-rice photos rejected by the gate      (want as high as possible)
  non-rice photos that ALSO pass the disease confidence threshold (the bad outcome)

    py scripts/eval_classifier.py [N_PER_GROUP]
"""

import os
import random
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend"))

from PIL import Image  # noqa: E402

from inference import get_gate, get_model  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
N = int(sys.argv[1]) if len(sys.argv) > 1 else 100
random.seed(12345)


def sample(folder: str, n: int) -> list[str]:
    files = [os.path.join(d, f) for d, _, fs in os.walk(folder) for f in fs if f.lower().endswith((".jpg", ".png"))]
    random.shuffle(files)
    return files[:n]


def main() -> None:
    gate, model = get_gate(), get_model()
    print(f"gate active={gate.is_active} threshold={gate.threshold}  disease model={model.model_mode}")
    threshold = float(os.environ.get("CONFIDENCE_THRESHOLD") or model.recommended_threshold or 60.0)

    groups = {"rice (Paddy Doctor)": sample(os.path.join(ROOT, "data", "train_images"), N * 3)}
    neg_root = os.path.join(ROOT, "data", "not_crop")
    for name in sorted(os.listdir(neg_root)):
        groups[f"non-rice: {name}"] = sample(os.path.join(neg_root, name), N)

    for name, files in groups.items():
        accepted = confident = 0
        for f in files:
            with Image.open(f) as im:
                ok, _ = gate.is_rice_leaf(im)
                if ok:
                    accepted += 1
                    if model.predict(im)[1] >= threshold:
                        confident += 1
        n = len(files)
        if name.startswith("rice"):
            print(f"{name:34s} accepted {accepted}/{n} = {accepted / n:.1%}")
        else:
            print(f"{name:34s} rejected {n - accepted}/{n} = {(n - accepted) / n:.1%}   "
                  f"still diagnosed confidently: {confident}/{n} = {confident / n:.1%}")


if __name__ == "__main__":
    main()
