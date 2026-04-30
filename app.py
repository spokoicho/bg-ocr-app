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
st.title("📄 Български OCR Екстрактор (подобрен)")

# Проверка на системните инструменти
t_path = shutil.which("tesseract")
p_path = shutil.which("pdftoppm")

if not t_path:
    st.error("❌ Tesseract не е намерен в системата!")
if not p_path:
    st.error("❌ Poppler (pdftoppm) не е намерен! OCR няма да работи.")

# Опит за извличане на директорията на Poppler (за Windows)
poppler_dir = None
if p_path:
    poppler_dir = os.path.dirname(p_path)

uploaded_file = st.file_uploader("Качете сканиран PDF", type=["pdf"])


def deskew_opencv(bgr_img):
    gray = cv2.cvtColor(bgr_img, cv2.COLOR_BGR2GRAY)
    coords = np.column_stack(np.where(gray < 255))
    if coords.size == 0:
        return bgr_img
    angle = cv2.minAreaRect(coords)[-1]

    if angle < -45:
        angle = -(90 + angle)
    else:
        angle = -angle

    (h, w) = bgr_img.shape[:2]
    M = cv2.getRotationMatrix2D((w // 2, h // 2), angle, 1.0)
    rotated = cv2.warpAffine(bgr_img, M, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)
    return rotated


def preprocess_pil_image(pil_img):
    # PIL → OpenCV BGR
    bgr = cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2BGR)

    # Deskew
    bgr = deskew_opencv(bgr)

    # Grayscale
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)

    # Adaptive threshold – много добро за сканирани документи
    thresh = cv2.adaptiveThreshold(
        gray, 255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY,
        31, 2
    )

    # Премахване на шум
    denoised = cv2.fastNlMeansDenoising(thresh, h=30)

    return denoised


if uploaded_file is not None:
    file_bytes = uploaded_file.read()

    if st.button("🚀 Извлечи текста"):
        try:
            # Записваме PDF временно
            with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
                tmp.write(file_bytes)
                tmp_path = tmp.name

            with st.spinner('Конвертиране на PDF в изображения (400 DPI)...'):
                convert_kwargs = {
                    "dpi": 400
                }
                if poppler_dir:
                    convert_kwargs["poppler_path"] = poppler_dir

                images = convert_from_path(tmp_path, **convert_kwargs)

            full_text = ""
            progress_bar = st.progress(0)

            for i, img in enumerate(images):
                processed = preprocess_pil_image(img)

                # OCR с LSTM engine и подходящ PSM
                text = pytesseract.image_to_string(
                    processed,
                    lang='bul',
                    config='--oem 1 --psm 6'
                )

                full_text += f"--- Страница {i+1} ---\n{text}\n\n"
                progress_bar.progress((i + 1) / len(images))

            if full_text.strip():
                st.success("Обработката завърши!")
                st.text_area("Резултат:", full_text, height=400)
                st.download_button("📥 Изтегли .txt", full_text.encode('utf-8'), "result.txt")
            else:
                st.warning("Не беше открит текст в документа.")

        except Exception:
            exc_type, exc_value, exc_traceback = sys.exc_info()
            st.error(f"⚠️ Истинската грешка е: {exc_value}")
            st.info("Ако грешката е 'PDFInfoNotInstalledError', значи Poppler не е в системния път.")
