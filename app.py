import streamlit as st
from streamlit_gsheets import GSheetsConnection
import pandas as pd
import pytesseract
from pdf2image import convert_from_bytes
import cv2
import numpy as np
import re
import xml.etree.ElementTree as ET
from xml.dom import minidom

# --- КОНФИГУРАЦИЯ ---
# Използваме URL адреса на вашата таблица
SHEET_URL = "https://docs.google.com/spreadsheets/d/1DxuWAgGtTwGUFxy_nntqDb_lMYbJVyTC1NSS3Rk62ps/edit?usp=sharing"

st.set_page_config(page_title="UBB Smart Converter", layout="wide")

# Инициализиране на връзката с Google Sheets
conn = st.connection("gsheets", type=GSheetsConnection)

def load_mappings():
    """Зарежда правилата от Google Sheets при стартиране."""
    try:
        # Четем данните с кратък кеш за актуалност
        df = conn.read(spreadsheet=SHEET_URL, ttl="5s")
        if df is not None and not df.empty:
            return dict(zip(df["Original"], df["Replacement"]))
    except Exception as e:
        st.error(f"Грешка при зареждане на базата данни: {e}")
    return {}

def save_mappings(mappings):
    """Записва новите правила обратно в Google Sheets чрез Service Account."""
    try:
        new_df = pd.DataFrame([
            {"Original": str(k), "Replacement": str(v)} 
            for k, v in mappings.items()
        ])
        # Обновяваме Sheet1 в Google Таблицата
        conn.update(spreadsheet=SHEET_URL, worksheet="Sheet1", data=new_df)
        st.cache_data.clear()
        st.success("✅ Базата данни в Google Sheets беше обновена!")
    except Exception as e:
        st.error(f"Грешка при запис в Google Sheets: {e}")

# --- OCR И ОБРАБОТКА НА PDF ---
def preprocess_image(img):
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    return gray

def ocr_pdf(pdf_bytes):
    pages = convert_from_bytes(pdf_bytes, dpi=400)
    full_text = ""
    for page in pages:
        img = np.array(page)
        processed = preprocess_image(img)
        full_text += pytesseract.image_to_string(processed, lang="bul+eng", config='--psm 6') + "\n"
    return full_text

def parse_statement(text, mappings):
    lines = [l.strip() for l in text.split('\n') if l.strip()]
    transactions = []
    
    for i, line in enumerate(lines):
        # Регулярен израз за дата и превръщане на 26 в 2026
        date_match = re.match(r"^(\d{2}/\d{2}/)(\d{2,4})", line)
        if date_match:
            day_month = date_match.group(1)
            year = date_match.group(2)
            full_year = year if len(year) == 4 else f"20{year}"
            formatted_date = f"{day_month}{full_year}"

            # Извличане на сума (премахване на интервали и запетаи)
            clean_line = line.replace(" ", "").replace(",", ".")
            amt_match = re.search(r"(-?\d+\.\d{2})EUR", clean_line)
            
            amount = 0.0
            if amt_match:
                amount = float(amt_match.group(1))

            # Вземане на име и основание от следващите редове
            raw_name = lines[i+1] if i+1 < len(lines) else ""
            raw_rem = lines[i+2] if i+2 < len(lines) else ""
            
            # Прилагане на автоматичните правила от Google Sheets
            name = mappings.get(raw_name, raw_name)
            rem = mappings.get(raw_rem, raw_rem)
            
            transactions.append({
                "ДАТА": formatted_date,
                "ОРИГИНАЛЕН ТЕКСТ": raw_name,
                "НАРЕДИТЕЛ/ПОЛУЧАТЕЛ": name,
                "ОСНОВАНИЕ": rem,
                "СУМА": amount,
                "ТИП": "Кредит" if amount > 0 else "Дебит"
            })
    return transactions

# --- ГЛАВЕН ИНТЕРФЕЙС ---
st.title("🏦 UBB Smart Converter & Memory")

# Зареждаме паметта в Session State
if 'mappings' not in st.session_state:
    st.session_state.mappings = load_mappings()

tab1, tab2 = st.tabs(["🚀 Конвертиране", "⚙️ Управление на правила"])

with tab1:
    uploaded_file = st.file_uploader("Качете PDF извлечение", type="pdf")

    if uploaded_file:
        if st.button("🔍 Анализирай PDF"):
            with st.spinner("Извличане на данни..."):
                raw_text = ocr_pdf(uploaded_file.read())
                data = parse_statement(raw_text, st.session_state.mappings)
                st.session_state.df = pd.DataFrame(data)

        if 'df' in st.session_state:
            st.subheader("📝 Редактиране на резултати")
            # Редактор на таблицата
            edited_df = st.data_editor(
                st.session_state.df,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "СУМА": st.column_config.NumberColumn(format="%.2f EUR"),
                }
            )

            if st.button("💾 Запамети промените в Google Sheets"):
                new_rules_found = False
                for _, row in edited_df.iterrows():
                    orig = row["ОРИГИНАЛЕН ТЕКСТ"]
                    curr = row["НАРЕДИТЕЛ/ПОЛУЧАТЕЛ"]
                    if orig != curr and orig != "":
                        st.session_state.mappings[orig] = curr
                        new_rules_found = True
                
                if new_rules_found:
                    save_mappings(st.session_state.mappings)
                else:
                    st.info("Няма открити нови промени за запис.")

            # XML Експорт
            if st.button("📦 Генерирай XML"):
                root = ET.Element("STATEMENT")
                for _, r in edited_df.iterrows():
                    t = ET.SubElement(root, "TRANSACTION")
                    ET.SubElement(t, "POST_DATE").text = r["ДАТА"]
                    tag = "AMOUNT_C" if r["ТИП"] == "Кредит" else "AMOUNT_D"
                    ET.SubElement(t, tag).text = str(abs(r["СУМА"]))
                    ET.SubElement(t, "NAME_R").text = r["НАРЕДИТЕЛ/ПОЛУЧАТЕЛ"]
                    ET.SubElement(t, "REM_I").text = r["ОСНОВАНИЕ"]
                
                xml_str = minidom.parseString(ET.tostring(root, encoding="utf-8")).toprettyxml(indent="  ")
                st.download_button("📥 Свали XML за счетоводство", xml_str, "export.xml", "text/xml")

with tab2:
    st.subheader("📚 Всички научени правила")
    st.write("Тук можете да редактирате или изтривате съществуващи правила директно в базата данни.")
    
    if st.session_state.mappings:
        rules_df = pd.DataFrame([
            {"Original": k, "Replacement": v} 
            for k, v in st.session_state.mappings.items()
        ])
        
        final_rules_df = st.data_editor(rules_df, use_container_width=True, num_rows="dynamic")
        
        if st.button("🛠️ Синхронизирай цялата база"):
            updated_map = dict(zip(final_rules_df["Original"], final_rules_df["Replacement"]))
            st.session_state.mappings = updated_map
            save_mappings(updated_map)
    else:
        st.info("Няма налични правила в Google Sheets.")
