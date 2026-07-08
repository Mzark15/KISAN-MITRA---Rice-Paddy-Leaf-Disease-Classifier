"""
Kisan Mitra — Paddy Disease Advisor
Upload a rice leaf photo → Keras classifier → diagnosis document → Groq summary → chat.

Run:  streamlit run app.py
"""

import json
import os
from datetime import datetime
from pathlib import Path

import numpy as np
import streamlit as st
from PIL import Image
from openai import OpenAI

# ── Config ────────────────────────────────────────────────────────────────────

MODEL_PATH    = os.environ.get("MODEL_PATH", "models/rice_disease_model.keras")
DISEASES_FILE = Path("diseases.json")
GROQ_API_KEY  = "" #os.environ.get("GROQ_API_KEY", "")
GROQ_MODEL    = os.environ.get("GROQ_MODEL", "meta-llama/llama-4-scout-17b-16e-instruct")

DISEASE_CLASSES = [
    "Bacterial Leaf Blight", "Bacterial Leaf Streak", "Bacterial Panicle Blight",
    "Black Stem Borer", "Blast", "Brown Spot", "Downy Mildew", "Hispa",
    "Leaf Roller", "Tungro", "White Stem Borer", "Yellow Stem Borer", "Normal",
]

MAX_CHAT_HISTORY = 10

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
    _, h, w, _ = model.input_shape
    img  = img.convert("RGB").resize((w, h), Image.Resampling.BILINEAR)
    arr  = np.array(img, dtype=np.float32)
    arr  = arr[..., ::-1]
    arr -= np.array([103.939, 116.779, 123.68], dtype=np.float32)
    arr  = np.expand_dims(arr, axis=0)
    probs = model.predict(arr, verbose=0)[0]
    idx   = int(np.argmax(probs))
    return DISEASE_CLASSES[idx], float(probs[idx]) * 100


# ── Diagnosis document ────────────────────────────────────────────────────────

def build_diagnosis_doc(disease: str, confidence: float, treatment: dict) -> str:
    date     = datetime.now().strftime("%Y-%m-%d %H:%M")
    severity = ", ".join(treatment.get("severity_levels", [])) or "varies"
    kvk_note = "\n⚠️ **KVK referral recommended.**" if treatment.get("refer_to_kvk") else ""

    if disease == "Normal":
        return f"""## Kisan Mitra Diagnosis Report
**Date:** {date}
**Result:** Plant appears healthy (Normal)
**Confidence:** {confidence:.1f}%

No disease detected. Continue regular monitoring and good agronomic practices.
"""

    return f"""## Kisan Mitra Diagnosis Report
**Date:** {date}
**Disease detected:** {disease}
**Confidence:** {confidence:.1f}%

### Cause
{treatment.get('cause', 'N/A')}

### Severity levels
{severity}

### Organic treatment
{treatment.get('organic_treatment', 'N/A')}

### Chemical treatment
{treatment.get('chemical_treatment', 'N/A')}

### Precautions
{treatment.get('precautions', 'Follow label instructions carefully.')}{kvk_note}
"""


# ── Groq helpers ──────────────────────────────────────────────────────────────

def groq_client() -> OpenAI:
    return OpenAI(base_url="https://api.groq.com/openai/v1", api_key=GROQ_API_KEY)


def get_summary(diagnosis_doc: str) -> str:
    if not GROQ_API_KEY:
        return "⚠️ GROQ_API_KEY not set. Add it to your .env file."

    system = (
        "You are Kisan Mitra, an AI advisor for paddy (rice) farmers in India. "
        "You have just received a diagnosis report for a farmer's crop. "
        "Write a SHORT, CLEAR advisory (3-5 sentences) in simple English based only on the report. "
        "Do not invent chemicals or dosages not mentioned in the report. "
        "For Tungro or Bacterial Panicle Blight, end with: "
        "'Please contact your nearest KVK or agricultural officer immediately.'"
    )
    resp = groq_client().chat.completions.create(
        model=GROQ_MODEL,
        messages=[
            {"role": "system", "content": system},
            {"role": "user",   "content": diagnosis_doc},
        ],
        max_tokens=300,
        temperature=0.4,
    )
    return resp.choices[0].message.content.strip()


def get_chat_reply(user_message: str, diagnosis_doc: str, history: list[dict]) -> str:
    system = f"""You are Kisan Mitra, an AI advisor for paddy (rice) farmers in India.

The farmer's crop has been analysed. Here is the diagnosis report — use this as context for all answers:

{diagnosis_doc}

Rules:
- Only answer questions about paddy/rice farming.
- Base treatment advice strictly on the diagnosis report above. Do not invent dosages.
- Keep answers short and practical (3-5 sentences).
- For Tungro or Bacterial Panicle Blight, always recommend consulting the nearest KVK.
"""
    messages = [{"role": "system", "content": system}]
    for turn in history[-MAX_CHAT_HISTORY:]:
        messages.append({"role": turn["role"], "content": turn["content"]})
    messages.append({"role": "user", "content": user_message})

    resp = groq_client().chat.completions.create(
        model=GROQ_MODEL,
        messages=messages,
        max_tokens=400,
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

# ── Session state init ────────────────────────────────────────────────────────

for key, default in {
    "diagnosis_doc": None,
    "disease":       None,
    "confidence":    0.0,
    "summary":       None,
    "chat_history":  [],
    "last_uploaded": None,
}.items():
    if key not in st.session_state:
        st.session_state[key] = default

# ── Upload + classify ─────────────────────────────────────────────────────────

uploaded = st.file_uploader("Upload a rice leaf photo", type=["jpg", "jpeg", "png", "webp"])

if uploaded:
    # Reset everything when a new image is uploaded
    if uploaded.name != st.session_state.last_uploaded:
        st.session_state.diagnosis_doc = None
        st.session_state.disease       = None
        st.session_state.confidence    = 0.0
        st.session_state.summary       = None
        st.session_state.chat_history  = []
        st.session_state.last_uploaded = uploaded.name

    img = Image.open(uploaded)
    st.image(img, caption="Uploaded photo", use_container_width=True)

    # Run classifier only once per upload
    if st.session_state.diagnosis_doc is None:
        with st.spinner("Classifying..."):
            disease, confidence = predict(img, model)

        treatment = diseases.get(disease, {})

        # Store everything directly — no parsing needed later
        st.session_state.disease       = disease
        st.session_state.confidence    = confidence
        st.session_state.diagnosis_doc = build_diagnosis_doc(disease, confidence, treatment)

    # Read back from session state
    disease    = st.session_state.disease
    confidence = st.session_state.confidence
    treatment  = diseases.get(disease, {})

    st.subheader(f"Detected: {disease}")
    st.progress(int(min(confidence, 100)), text=f"Confidence: {confidence:.1f}%")

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

    # ── Summary ───────────────────────────────────────────────────────────────

    st.divider()

    if st.session_state.summary is None:
        with st.spinner("Getting advisor summary..."):
            st.session_state.summary = get_summary(st.session_state.diagnosis_doc)

    st.subheader("Advisor Summary")
    st.write(st.session_state.summary)

    # ── Chat ──────────────────────────────────────────────────────────────────

    st.divider()
    st.subheader("💬 Ask a follow-up question")
    st.caption("The advisor knows your diagnosis and will answer based on it.")

    if not GROQ_API_KEY:
        st.warning("Set GROQ_API_KEY in .env to enable chat.")
    else:
        for turn in st.session_state.chat_history:
            with st.chat_message(turn["role"]):
                st.write(turn["content"])

        user_input = st.chat_input("Ask about your crop...")

        if user_input:
            with st.chat_message("user"):
                st.write(user_input)

            st.session_state.chat_history.append({"role": "user", "content": user_input})

            with st.chat_message("assistant"):
                with st.spinner("Thinking..."):
                    reply = get_chat_reply(
                        user_input,
                        st.session_state.diagnosis_doc,
                        st.session_state.chat_history[:-1],
                    )
                st.write(reply)

            st.session_state.chat_history.append({"role": "assistant", "content": reply})

        if st.session_state.chat_history:
            if st.button("Clear chat", type="secondary"):
                st.session_state.chat_history = []
                st.rerun()

    # ── Download report ───────────────────────────────────────────────────────

    st.divider()
    st.download_button(
        label="📄 Download diagnosis report",
        data=st.session_state.diagnosis_doc,
        file_name=f"kisan_mitra_{datetime.now().strftime('%Y%m%d_%H%M')}.md",
        mime="text/markdown",
    )