import streamlit as st
import pytesseract
from pdf2image import convert_from_path
import shutil
import sys
import tempfile
import os

import cv2
import numpy as np

st.set_page_config(page_title="Български OCR", layout="centered")
st.title("📄 Подобрен OCR за банкови PDF извлечения")

# Проверка за Tesseract и Poppler
t_path = shutil.which("tesseract")
p_path = shutil.which("pdftoppm")

if not t_path:
    st.error("❌ Tesseract не е намерен!")
if not p_path:
    st.error("❌ Poppler (pdftoppm) липсва – PDF няма да се конвертира!")

# Определяне на Poppler директорията (Windows)
poppler_dir = None
if p_path:
    poppler_dir = os.path.dirname(p_path)


# -----------------------------
# OCR PREPROCESSING FUNCTIONS
# -----------------------------

def deskew(image):
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    coords = np.column_stack(np.where(gray < 255))
    if coords.size == 0:
        return image
    angle = cv2.minAreaRect(coords)[-1]

    if angle < -45:
        angle = -(90 + angle)
    else:
        angle = -angle

    (h, w) = image.shape[:2]
    M = cv2.getRotationMatrix2D((w // 2, h // 2), angle, 1.0)
    rotated = cv2.warpAffine(image, M, (w, h),
                             flags=cv2.INTER_CUBIC,
                             borderMode=cv2.BORDER_REPLICATE)
    return rotated


def preprocess(pil_img):
    # PIL → OpenCV
    img = cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2BGR)

    # Deskew
    img = deskew(img)

    # Grayscale
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    # Увеличаване на контраста
    clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
    gray = clahe.apply(gray)

    # Adaptive threshold – най-добро за банкови PDF-и
    thresh = cv2.adaptiveThreshold(
        gray, 255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY,
        31, 8
    )

    # Премахване на шум
    denoised = cv2.fastNlMeansDenoising(thresh, h=25)

    return denoised


# -----------------------------
# STREAMLIT UI
# -----------------------------

uploaded_file = st.file_uploader("Качи PDF извлечение", type=["pdf"])

if uploaded_file is not None:
    file_bytes = uploaded_file.read()

    if st.button("🚀 Стартирай OCR"):
        try:
            # Записваме PDF временно
            with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
                tmp.write(file_bytes)
                tmp_path = tmp.name

            # Конвертиране на PDF → изображения
            with st.spinner("Конвертиране на PDF (400 DPI)..."):
                kwargs = {"dpi": 400}
                if poppler_dir:
                    kwargs["poppler_path"] = poppler_dir

                images = convert_from_path(tmp_path, **kwargs)

            full_text = ""
            progress = st.progress(0)

            for i, img in enumerate(images):
                processed = preprocess(img)

                # OCR с комбиниран език (много важно за ОББ)
                text = pytesseract.image_to_string(
                    processed,
                    lang="bul+eng",
                    config="--oem 1 --psm 6"
                )

                full_text += f"--- Страница {i+1} ---\n{text}\n\n"
                progress.progress((i + 1) / len(images))

            st.success("Готово!")
            st.text_area("Резултат:", full_text, height=450)
            st.download_button("📥 Изтегли TXT", full_text.encode("utf-8"), "ocr_result.txt")

        except Exception:
            exc_type, exc_value, exc_traceback = sys.exc_info()
            st.error(f"⚠️ Грешка: {exc_value}")
            st.info("Ако е PDFInfoNotInstalledError → Poppler не е в PATH.")
