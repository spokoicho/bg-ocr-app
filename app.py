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

# --- ВРЪЗКА С GOOGLE SHEETS ---
conn = st.connection("gsheets", type=GSheetsConnection)

def load_mappings():
    """Зарежда правилата от линка, който дадохте."""
    try:
        df = conn.read(ttl="10s") # Четем с кратък кеш за актуалност
        # Очакваме колони 'Original' и 'Replacement'
        return dict(zip(df["Original"], df["Replacement"]))
    except Exception as e:
        st.error(f"Грешка при зареждане на таблицата: {e}")
        return {}

def save_mappings_to_sheets(all_mappings_dict):
    """Записва целия обновен речник обратно в Google Sheets."""
    new_df = pd.DataFrame([
        {"Original": k, "Replacement": v} for k, v in all_mappings_dict.items()
    ])
    conn.update(data=new_df)
    st.cache_data.clear()

# --- OCR И ПАРСВАНЕ ---
def ocr_pdf(pdf_bytes):
    pages = convert_from_bytes(pdf_bytes, dpi=300)
    full_text = ""
    for page in pages:
        img = np.array(page)
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        full_text += pytesseract.image_to_string(gray, lang="bul+eng", config='--psm 6') + "\n"
    return full_text

def parse_statement(text, mappings):
    lines = [l.strip() for l in text.split('\n') if l.strip()]
    transactions = []
    for i, line in enumerate(lines):
        date_match = re.match(r"^(\d{2}/\d{2}/\d{2,4})", line)
        if date_match:
            # Вземаме следващите редове за детайли[cite: 2, 5]
            raw_name = lines[i+1] if i+1 < len(lines) else ""
            raw_rem = lines[i+2] if i+2 < len(lines) else ""
            
            # Прилагаме автоматичните замени[cite: 4]
            name = mappings.get(raw_name, raw_name)
            rem = mappings.get(raw_rem, raw_rem)
            
            transactions.append({
                "ДАТА": date_match.group(1),
                "ОРИГИНАЛЕН ТЕКСТ": raw_name, # Пазим го за справка при запис
                "НАРЕДИТЕЛ/ПОЛУЧАТЕЛ": name,
                "ОСНОВАНИЕ": rem,
                "СУМА": 0.0,
                "ТИП": "Дебит"
            })
    return transactions

# --- UI ИНТЕРФЕЙС ---
st.title("🏦 Смарт Конвертор с Google Sheets")

# Зареждаме правилата в сесията
if 'mappings' not in st.session_state:
    st.session_state.mappings = load_mappings()

tab1, tab2 = st.tabs(["🚀 Обработка", "⚙️ База Данни"])

with tab1:
    uploaded_file = st.file_uploader("Качете PDF", type="pdf")
    if uploaded_file:
        if st.button("Анализирай"):
            raw_text = ocr_pdf(uploaded_file.read())
            data = parse_statement(raw_text, st.session_state.mappings)
            st.session_state.df = pd.DataFrame(data)

        if 'df' in st.session_state:
            # Интерактивна таблица за промени[cite: 1]
            edited_df = st.data_editor(st.session_state.df, use_container_width=True, hide_index=True)
            
            if st.button("💾 Запамети новите имена завинаги"):
                updated = False
                for _, row in edited_df.iterrows():
                    orig = row["ОРИГИНАЛЕН ТЕКСТ"]
                    current = row["НАРЕДИТЕЛ/ПОЛУЧАТЕЛ"]
                    if orig != current and orig != "":
                        st.session_state.mappings[orig] = current
                        updated = True
                
                if updated:
                    save_mappings_to_sheets(st.session_state.mappings)
                    st.success("Правилата са изпратени в Google Sheets!")

with tab2:
    st.subheader("Списък с всички активни правила")
    if st.session_state.mappings:
        # Позволяваме директна редакция на базата данни[cite: 1, 4]
        rules_df = pd.DataFrame([
            {"Original": k, "Replacement": v} for k, v in st.session_state.mappings.items()
        ])
        edited_rules = st.data_editor(rules_df, use_container_width=True, num_rows="dynamic")
        
        if st.button("🛠️ Обнови цялата база данни"):
            new_map = dict(zip(edited_rules["Original"], edited_rules["Replacement"]))
            save_mappings_to_sheets(new_map)
            st.session_state.mappings = new_map
            st.toast("Базата данни е синхронизирана!")
