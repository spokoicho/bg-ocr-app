import streamlit as st
import pytesseract
from pdf2image import convert_from_bytes
import cv2
import numpy as np
import re
import pandas as pd
import xml.etree.ElementTree as ET
from xml.dom import minidom

# --- КОНФИГУРАЦИЯ НА СТРАНИЦАТА ---
st.set_page_config(page_title="UBB PDF to XML & Table", layout="wide")

def preprocess_image_for_rows(img):
    """Подобряване на изображението за по-добър OCR[cite: 1]."""
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    denoised = cv2.fastNlMeansDenoising(gray, None, 10, 7, 21)
    _, thresh = cv2.threshold(denoised, 180, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    return thresh

def ocr_pdf(pdf_bytes):
    """Конвертиране на PDF в текст с висока резолюция."""
    pages = convert_from_bytes(pdf_bytes, dpi=400)
    full_text = ""
    for page in pages:
        img = np.array(page)
        processed = preprocess_image_for_rows(img)
        # PSM 6 е подходящ за таблични данни по редове[cite: 1]
        text = pytesseract.image_to_string(processed, lang="bul+eng", config='--oem 3 --psm 6')
        full_text += text + "\n"
    
    # Корекция на често срещани OCR грешки[cite: 2, 3]
    full_text = full_text.replace("CENA", "СЕПА").replace("580.", "SBD.")
    return full_text

def parse_obb_statement(text):
    """Парсване на извлечения текст към структурирани трансакции."""
    iban_match = re.search(r"IBAN\s*:\s*(BG\d{2}UBBS\d{14})", text)
    iban = iban_match.group(1) if iban_match else "Неизвестен"
    
    transactions = []
    lines = [l.strip() for l in text.split('\n') if l.strip()]
    
    i = 0
    while i < len(lines):
        line = lines[i]
        # Търсим начало на ред с дата (напр. 01/01/2026 или 01/01/26)[cite: 2]
        match = re.match(r"^(\d{2}/\d{2}/\d{2,4})", line)
        
        if match:
            tr = {
                "post_date": match.group(1), 
                "ref": "null", 
                "name": "null", 
                "rem1": "null", 
                "tr_name": "ОПЕРАЦИЯ", 
                "amt": "0.00", 
                "type": "C"
            }
            
            # Извличане на сума и определяне на Дебит/Кредит[cite: 2, 5]
            amt_match = re.search(r"(-?[\d\s,]+\.\d{2})\s*EUR", line.replace(",", ""))
            if amt_match:
                val_str = amt_match.group(1).replace(" ", "")
                val_float = float(val_str)
                tr["amt"] = f"{abs(val_float):.2f}"
                tr["type"] = "D" if val_float < 0 else "C"
            
            # Извличане на вид операция (напр. СЕПА ПОЛУЧЕН)
            types = ["СЕПА ПОЛУЧЕН", "ИЗХОДЯЩ ПРЕВОД СЕПА", "МЕСЕЧНА ТАКСА", "ТЕГЛЕНЕ ОТ АТМ", "ПРЕВАЛУТИРАНЕ"]
            for t in types:
                if t in line.upper():
                    tr["tr_name"] = t
                    break

            # Търсене на Наредител/Основание на следващите редове[cite: 2, 5]
            curr_j = i + 1
            extra_info = []
            while curr_j < len(lines) and not re.match(r"^\d{2}/\d{2}/\d{2}", lines[curr_j]):
                extra_info.append(lines[curr_j])
                curr_j += 1
            
            if len(extra_info) >= 1: tr["name"] = extra_info[0]
            if len(extra_info) >= 2: tr["rem1"] = extra_info[1]
            
            transactions.append(tr)
            i = curr_j - 1
        i += 1
        
    return iban, transactions

def generate_xml_final(iban, trs):
    """Генериране на XML структура."""
    root = ET.Element("STATEMENT")
    ET.SubElement(root, "IBAN_S").text = iban
    
    for t in trs:
        tran = ET.SubElement(root, "TRANSACTION")
        ET.SubElement(tran, "POST_DATE").text = t["post_date"]
        # Разделяне на сумите в правилните тагове[cite: 4]
        if t["type"] == "C":
            ET.SubElement(tran, "AMOUNT_C").text = t["amt"]
        else:
            ET.SubElement(tran, "AMOUNT_D").text = t["amt"]
        
        ET.SubElement(tran, "TR_NAME").text = t["tr_name"]
        ET.SubElement(tran, "NAME_R").text = t["name"]
        ET.SubElement(tran, "REM_I").text = t["rem1"]
        ET.SubElement(tran, "REFERENCE").text = t["ref"]

    xml_str = ET.tostring(root, encoding="utf-8")
    return minidom.parseString(xml_str).toprettyxml(indent="  ")

def display_styled_table(trs):
    """Визуализация в таблица според примера на потребителя[cite: 1, 4]."""
    df_data = []
    for t in trs:
        amt_prefix = "+" if t["type"] == "C" else "-"
        df_data.append({
            "ДАТА": t["post_date"],
            "ЧАС": "null",
            "ВИД": t["tr_name"],
            "НАРЕДИТЕЛ/ПОЛУЧАТЕЛ": t["name"],
            "ОСНОВАНИЕ": t["rem1"],
            "СУМА": f"{amt_prefix}{t['amt']}",
            "ТИП": "Кредит" if t["type"] == "C" else "Дебит"
        })
    
    df = pd.DataFrame(df_data)

    def color_amounts(val):
        color = 'green' if '+' in str(val) else 'red' if '-' in str(val) else 'black'
        return f'color: {color}; font-weight: bold'

    styled_df = df.style.applymap(color_amounts, subset=['СУМА'])
    st.subheader("📊 Преглед на извлечените данни")
    st.dataframe(styled_df, use_container_width=True, hide_index=True)

# --- ГЛАВЕН ИНТЕРФЕЙС ---
st.title("🏦 ОББ Извлечение: PDF ➔ XML & Таблица")
st.markdown("Качете вашето банково извлечение в PDF формат за автоматично преобразуване.")

uploaded_file = st.file_uploader("Изберете PDF файл", type="pdf")

if uploaded_file:
    with st.spinner('Анализиране на документа...'):
        # 1. OCR обработка[cite: 1, 3]
        text_data = ocr_pdf(uploaded_file.read())
        
        # 2. Парсване[cite: 2, 5]
        iban, transactions = parse_obb_statement(text_data)
        
        if transactions:
            # 3. Визуализация в таблица[cite: 4]
            display_styled_table(transactions)
            
            # 4. XML Генериране[cite: 4]
            xml_output = generate_xml_final(iban, transactions)
            
            st.divider()
            col1, col2 = st.columns(2)
            with col1:
                st.download_button(
                    label="📥 Свали XML файл",
                    data=xml_output,
                    file_name=f"OBB_Statement_{iban}.xml",
                    mime="text/xml"
                )
            with col2:
                if st.checkbox("Покажи XML код"):
                    st.code(xml_output, language="xml")
        else:
            st.error("Не бяха намерени трансакции. Моля, уверете се, че PDF файлът е оригинално извлечение от ОББ.")
