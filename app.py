"""
Kisan Mitra — Paddy Disease Advisor
Upload a rice leaf photo → Keras classifier → Groq summary.

Run:  streamlit run app.py
"""

import json
import os
from pathlib import Path

import numpy as np
import streamlit as st
from PIL import Image
from openai import OpenAI

# ── Config ────────────────────────────────────────────────────────────────────

MODEL_PATH    = os.environ.get("MODEL_PATH", "models/rice_disease_model.keras")
DISEASES_FILE = Path("diseases.json")
GROQ_API_KEY  = "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" #os.environ.get("GROQ_API_KEY", "")
GROQ_MODEL    = os.environ.get("GROQ_MODEL", "meta-llama/llama-4-scout-17b-16e-instruct")
INPUT_SIZE    = int(os.environ.get("MODEL_INPUT_SIZE", "256"))

DISEASE_CLASSES = [
    "Bacterial Leaf Blight", "Bacterial Leaf Streak", "Bacterial Panicle Blight",
    "Black Stem Borer", "Blast", "Brown Spot", "Downy Mildew", "Hispa",
    "Leaf Roller", "Tungro", "White Stem Borer", "Yellow Stem Borer", "Normal",
]

# ── Load model (cached — runs once) ──────────────────────────────────────────

@st.cache_resource
def load_model():
    if not Path(MODEL_PATH).is_file():
        return None
    import tensorflow as tf
    return tf.keras.models.load_model(MODEL_PATH)


@st.cache_data
def load_diseases():
    with open(DISEASES_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


# ── Classifier ────────────────────────────────────────────────────────────────

def predict(img: Image.Image, model) -> tuple[str, float]:
    # Read the size the model actually expects — ignore INPUT_SIZE env var
    _, h, w, _ = model.input_shape
    img  = img.convert("RGB").resize((w, h), Image.Resampling.BILINEAR)
    arr  = np.array(img, dtype=np.float32)

    # ResNet ImageNet preprocessing (caffe/BGR mode)
    arr  = arr[..., ::-1]   # RGB → BGR
    arr -= np.array([103.939, 116.779, 123.68], dtype=np.float32)
    arr  = np.expand_dims(arr, axis=0)

    probs = model.predict(arr, verbose=0)[0]
    idx   = int(np.argmax(probs))
    return DISEASE_CLASSES[idx], float(probs[idx]) * 100


# ── Groq summary ──────────────────────────────────────────────────────────────

def get_summary(disease: str, confidence: float, treatment: dict) -> str:
    if not GROQ_API_KEY:
        return "⚠️ GROQ_API_KEY not set. Add it to your .env file."

    client = OpenAI(base_url="https://api.groq.com/openai/v1", api_key=GROQ_API_KEY)

    prompt = f"""You are Kisan Mitra, an AI advisor for paddy (rice) farmers in India.

The classifier identified: {disease} (confidence: {confidence:.1f}%)

Treatment data:
- Cause: {treatment.get('cause', '')}
- Severity levels: {', '.join(treatment.get('severity_levels', []))}
- Organic treatment: {treatment.get('organic_treatment', '')}
- Chemical treatment: {treatment.get('chemical_treatment', '')}
- Precautions: {treatment.get('precautions', 'Follow label instructions.')}

Write a SHORT, CLEAR advisory for the farmer in simple English (3-5 sentences).
Only use the treatment data above. Do not invent chemicals or dosages.
If the disease is Tungro or Bacterial Panicle Blight, end with:
"Please contact your nearest KVK or agricultural officer immediately."
If the plant is Normal/Healthy, say the plant looks healthy and suggest monitoring.
"""
    resp = client.chat.completions.create(
        model=GROQ_MODEL,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=300,
        temperature=0.4,
    )
    return resp.choices[0].message.content.strip()


# ── Streamlit UI ──────────────────────────────────────────────────────────────

st.set_page_config(page_title="Kisan Mitra", page_icon="🌾", layout="centered")
st.title("🌾 Kisan Mitra")
st.caption("Upload a rice leaf photo to detect disease and get treatment advice.")

model    = load_model()
diseases = load_diseases()

if model is None:
    st.error(
        "❌ Model not found. Place `rice_disease_model.keras` in the `models/` folder.\n\n"
        "In Colab run:\n```python\nmodel.save('rice_disease_model.keras')\n"
        "from google.colab import files\nfiles.download('rice_disease_model.keras')\n```"
    )
    st.stop()

uploaded = st.file_uploader("Upload a rice leaf photo", type=["jpg", "jpeg", "png", "webp"])

if uploaded:
    img = Image.open(uploaded)
    st.image(img, caption="Uploaded photo", use_container_width=True)

    with st.spinner("Classifying..."):
        disease, confidence = predict(img, model)

    st.subheader(f"Detected: {disease}")
    st.progress(int(confidence), text=f"Confidence: {confidence:.1f}%")

    treatment = diseases.get(disease, {})

    if disease != "Normal" and treatment:
        with st.expander("Treatment details", expanded=True):
            st.markdown(f"**Cause:** {treatment.get('cause', 'N/A')}")
            st.markdown(f"**Organic treatment:** {treatment.get('organic_treatment', 'N/A')}")
            st.markdown(f"**Chemical treatment:** {treatment.get('chemical_treatment', 'N/A')}")
            if treatment.get("precautions"):
                st.markdown(f"**Precautions:** {treatment['precautions']}")
            if treatment.get("refer_to_kvk"):
                st.warning("⚠️ Serious disease — contact your nearest KVK immediately.")
    else:
        st.success("✅ Plant appears healthy. Keep monitoring regularly.")

    st.divider()
    with st.spinner("Getting advisor summary..."):
        summary = get_summary(disease, confidence, treatment)
    st.subheader("Advisor Summary")
    st.write(summary)
