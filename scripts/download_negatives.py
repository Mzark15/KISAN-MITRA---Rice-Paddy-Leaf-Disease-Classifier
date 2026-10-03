"""Download "not a rice leaf" images into data/not_crop/<set>/ for scripts/train_crop_gate.py.

Mix: textures (DTD), everyday objects/animals/vehicles (STL10, Caltech101), and other crops'
leaves (PlantVillage — the hardest negatives, since a farmer may photograph the wrong plant).

    py scripts/download_negatives.py
"""

import io
import os
import random

import pyarrow.parquet as pq
from huggingface_hub import hf_hub_download, list_repo_files
from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "data", "not_crop")

# repo, parquet files (None = every parquet under data/), max images to keep
SOURCES = [
    ("tanganke/dtd", None, 2500),
    ("tanganke/stl10", ["data/train-00000-of-00001.parquet"], 2500),
    ("dpdl-benchmark/caltech101", ["data/train-00000-of-00001.parquet"], 2500),
    ("GVJahnavi/PlantVillage_dataset", ["data/test-00000-of-00001.parquet"], 3000),
]

random.seed(0)


def image_column(table) -> str:
    for name in table.column_names:
        if name in ("image", "img"):
            return name
    raise KeyError(f"no image column in {table.column_names}")


def save_set(repo: str, files: list[str] | None, cap: int) -> None:
    name = repo.split("/")[-1]
    dest = os.path.join(OUT, name)
    if os.path.isdir(dest) and len(os.listdir(dest)) >= min(cap, 500):
        print(f"{name}: already there, skipping")
        return
    os.makedirs(dest, exist_ok=True)
    if files is None:
        files = [f for f in list_repo_files(repo, repo_type="dataset") if f.endswith(".parquet")]
    random.shuffle(files)
    saved = 0
    for f in files:
        path = hf_hub_download(repo, f, repo_type="dataset")
        pf = pq.ParquetFile(path)
        col = image_column(pf.schema_arrow.empty_table())
        per_file = max(1, (cap - saved) // max(1, len(files)))
        for batch in pf.iter_batches(batch_size=256, columns=[col]):
            for cell in batch.column(0).to_pylist():
                if saved >= cap or per_file <= 0:
                    break
                if random.random() > 0.5 and len(files) > 1:
                    continue
                try:
                    Image.open(io.BytesIO(cell["bytes"])).convert("RGB").save(
                        os.path.join(dest, f"{saved:05d}.jpg"), quality=90
                    )
                    saved += 1
                    per_file -= 1
                except Exception:
                    continue
            if saved >= cap or per_file <= 0:
                break
        if saved >= cap:
            break
    print(f"{name}: saved {saved} images")


if __name__ == "__main__":
    for repo, files, cap in SOURCES:
        try:
            save_set(repo, files, cap)
        except Exception as exc:  # one dead source shouldn't stop the others
            print(f"{repo}: FAILED ({exc!r})")
