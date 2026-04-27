import streamlit as st
import pytesseract
from pdf2image import convert_from_path

st.set_page_config(page_title="BG OCR")
st.title("📄 Български OCR")

file = st.file_uploader("Качете PDF", type=["pdf"])

if file:
    if st.button("🚀 Стартирай"):
        try:
            with st.spinner('Обработка...'):
                # Четем съдържанието
                images = convert_from_path(file.read(), dpi=300)
                full_text = ""
                for img in images:
                    full_text += pytesseract.image_to_string(img, lang='bul') + "\n\n"
                
                st.success("Готово!")
                st.text_area("Текст:", full_text, height=400)
        except Exception as e:
            # Използваме 'e', а не 'err'!
            st.error(f"Грешка: {str(e)}")