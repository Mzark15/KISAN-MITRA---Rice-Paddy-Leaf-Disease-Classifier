import json
from pathlib import Path

from fastapi import APIRouter

router = APIRouter()

BASE_DIR = Path(__file__).resolve().parent.parent
DISEASES_FILE = BASE_DIR / "diseases.json"


def load_diseases() -> dict:
    with open(DISEASES_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


@router.get("/diseases")
def get_diseases():
    return load_diseases()
