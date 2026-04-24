import streamlit as st
import pytesseract
from pdf2image import convert_from_path

st.set_page_config(page_title="OCR Tool")
st.title("📄 Български OCR")

file = st.file_uploader("Качете PDF", type=["pdf"])

if file:
    if st.button("Извлечи текста"):
        try:
            with st.spinner("Работя..."):
                # Конвертиране
                images = convert_from_path(file.read(), dpi=300)
                final_text = ""
                
                for img in images:
                    # Директно извличане
                    text = pytesseract.image_to_string(img, lang='bul')
                    final_text += text + "\n\n"
                
                st.success("Готово!")
                st.text_area("Резултат:", final_text, height=300)
        except Exception:
            # Тук не ползваме никакви променливи (като e или err)
            # за да е невъзможно да се появи същата грешка
            st.error("Възникна технически проблем. Проверете дали файлът е сканиран PDF.")
