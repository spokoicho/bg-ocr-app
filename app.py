import streamlit as st
import pytesseract
from pdf2image import convert_from_path
import shutil
import sys
import tempfile
import os
import cv2
import numpy as np

st.set_page_config(page_title="Банков OCR – стабилна версия", layout="centered")
st.title("📄 OCR за банкови PDF извлечения (златна среда)")

# Проверка за Tesseract и Poppler
t_path = shutil.which("tesseract")
p_path = shutil.which("pdftoppm")

if not t_path:
    st.error("❌ Tesseract не е намерен!")
if not p_path:
    st.error("❌ Poppler липсва – PDF няма да се конвертира!")

poppler_dir = os.path.dirname(p_path) if p_path else None


# -----------------------------
# УМЕРЕН PREPROCESSING
# -----------------------------

def deskew(image):
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    coords = np.column_stack(np.where(gray < 255))
    if coords.size == 0:
        return image
    angle = cv2.minAreaRect(coords)[-1]
    angle = -(90 + angle) if angle < -45 else -angle
    (h, w) = image.shape[:2]
    M = cv2.getRotationMatrix2D((w // 2, h // 2), angle, 1.0)
    return cv2.warpAffine(image, M, (w, h),
                          flags=cv2.INTER_CUBIC,
                          borderMode=cv2.BORDER_REPLICATE)


def preprocess_moderate(pil_img):
    img = cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2BGR)

    img = deskew(img)

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    # Лек контраст (без агресивно чистене)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    gray = clahe.apply(gray)

    # Умерен adaptive threshold
    thresh = cv2.adaptiveThreshold(
        gray, 255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY,
        31, 5
    )

    # Леко denoising (h=15 не изяжда букви)
    denoised = cv2.fastNlMeansDenoising(thresh, h=15)

    return denoised


# -----------------------------
# OCR
# -----------------------------

def ocr_text(image):
    return pytesseract.image_to_string(
        image,
        lang="bul+eng",
        config="--oem 1 --psm 4"
    )


# -----------------------------
# STREAMLIT UI
# -----------------------------

uploaded_file = st.file_uploader("Качи PDF извлечение", type=["pdf"])

if uploaded_file is not None:
    file_bytes = uploaded_file.read()

    if st.button("🚀 Стартирай OCR"):
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
                tmp.write(file_bytes)
                tmp_path = tmp.name

            with st.spinner("Конвертиране на PDF (400 DPI)..."):
                kwargs = {"dpi": 400}
                if poppler_dir:
                    kwargs["poppler_path"] = poppler_dir
                images = convert_from_path(tmp_path, **kwargs)

            full_text = ""
            progress = st.progress(0)

            for i, img in enumerate(images):
                processed = preprocess_moderate(img)

                text = ocr_text(processed)

                full_text += f"--- Страница {i+1} ---\n{text}\n\n"
                progress.progress((i + 1) / len(images))

            st.success("Готово!")
            st.text_area("Резултат:", full_text, height=450)
            st.download_button("📥 Изтегли TXT", full_text.encode("utf-8"), "ocr_result.txt")

        except Exception:
            exc_type, exc_value, exc_traceback = sys.exc_info()
            st.error(f"⚠️ Грешка: {exc_value}")
