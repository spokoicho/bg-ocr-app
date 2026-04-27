import streamlit as st
import pytesseract
from pdf2image import convert_from_path

st.title("📄 Български OCR")

file = st.file_uploader("Качете PDF", type=["pdf"])

if file:
    if st.button("🚀 Стартирай"):
        try:
            with st.spinner('Обработка...'):
                images = convert_from_path(file.read(), dpi=300)
                text = ""
                for img in images:
                    text += pytesseract.image_to_string(img, lang='bul') + "\n\n"
                st.success("Готово!")
                st.text_area("Извлечен текст:", text, height=400)
        except Exception as e:
            st.error(f"Грешка: {str(e)}")
