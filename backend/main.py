from fastapi import FastAPI, File, UploadFile, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import json
import os
import numpy as np
from PIL import Image
import io
import uvicorn

app = FastAPI(title="Kisan Mitra - Disease Detection API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

DISEASE_CLASSES = [
    "Leaf Blast",
    "Bacterial Leaf Blight",
    "Brown Spot",
    "Tungro",
    "Sheath Blight",
    "Healthy"
]

DISEASES_FILE = os.path.join(os.path.dirname(__file__), "diseases.json")

def load_diseases():
    with open(DISEASES_FILE, "r") as f:
        return json.load(f)

@app.get("/diseases")
def get_diseases():
    return load_diseases()

@app.post("/diagnose")
async def diagnose(image: UploadFile = File(...)):
    try:
        contents = await image.read()
        img = Image.open(io.BytesIO(contents))
        img.verify()
        img = Image.open(io.BytesIO(contents))
        img = img.convert("RGB")
        
        # Placeholder for actual model inference
        # In real usage, this is where you'd load and run your TFLite model
        # For now, returning random values for demonstration
        np.random.seed(42)
        confidences = np.random.rand(len(DISEASE_CLASSES))
        confidences = confidences / confidences.sum()
        predicted_idx = int(np.argmax(confidences))
        disease_name = DISEASE_CLASSES[predicted_idx]
        confidence = float(confidences[predicted_idx]) * 100
        
        diseases = load_diseases()
        treatment_info = diseases.get(disease_name, {})
        
        return {
            "disease": disease_name,
            "confidence": round(confidence, 2),
            "treatment": treatment_info
        }
    
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid image: {str(e)}")

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
