import streamlit as st
import pytesseract
from pdf2image import convert_from_bytes
import cv2
import numpy as np
import re
import pandas as pd
import xml.etree.ElementTree as ET
from xml.dom import minidom

# --- КОНФИГУРАЦИЯ ---
st.set_page_config(page_title="UBB Statement Converter", layout="wide")

def preprocess_image(img):
    """Оптимизация на изображението за OCR."""
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    denoised = cv2.fastNlMeansDenoising(gray, None, 10, 7, 21)
    _, thresh = cv2.threshold(denoised, 180, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    return thresh

def ocr_pdf(pdf_bytes):
    """Конвертиране на PDF в текст[cite: 1, 3]."""
    pages = convert_from_bytes(pdf_bytes, dpi=400)
    full_text = ""
    for page in pages:
        img = np.array(page)
        processed = preprocess_image(img)
        # Използваме PSM 6 за запазване на редовата структура[cite: 1]
        text = pytesseract.image_to_string(processed, lang="bul+eng", config='--oem 3 --psm 6')
        full_text += text + "\n"
    
    # Корекция на OCR грешки[cite: 2, 3]
    full_text = full_text.replace("CENA", "СЕПА").replace("580.", "SBD.")
    return full_text

def parse_obb_statement(text):
    """Извличане на трансакции и IBAN[cite: 2, 5]."""
    iban_match = re.search(r"IBAN\s*:\s*(BG\d{2}UBBS\d{14})", text)
    iban = iban_match.group(1) if iban_match else "Неизвестен"
    
    transactions = []
    lines = [l.strip() for l in text.split('\n') if l.strip()]
    
    i = 0
    while i < len(lines):
        line = lines[i]
        # Маски за дата: DD/MM/YYYY или DD/MM/YY[cite: 2]
        date_match = re.match(r"^(\d{2}/\d{2}/\d{2,4})", line)
        
        if date_match:
            tr = {
                "post_date": date_match.group(1), 
                "ref": "null", 
                "name": "null", 
                "rem1": "null", 
                "tr_name": "ОПЕРАЦИЯ", 
                "amt": "0.00", 
                "type": "C"
            }
            
            # Търсене на сума (напр. -123.45 EUR)[cite: 2, 5]
            amt_match = re.search(r"(-?[\d\s,]+\.\d{2})\s*EUR", line.replace(",", ""))
            if amt_match:
                val_str = amt_match.group(1).replace(" ", "")
                val_float = float(val_str)
                tr["amt"] = f"{abs(val_float):.2f}"
                tr["type"] = "D" if val_float < 0 else "C"
            
            # Определяне на типа операция
            op_types = ["СЕПА ПОЛУЧЕН", "ИЗХОДЯЩ ПРЕВОД СЕПА", "МЕСЕЧНА ТАКСА", "ТЕГЛЕНЕ ОТ АТМ", "ПРЕВАЛУТИРАНЕ"]
            for op in op_types:
                if op in line.upper():
                    tr["tr_name"] = op
                    break

            # Четем следващите редове за Име и Основание[cite: 2, 5]
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

def generate_xml(iban, trs):
    """Създаване на XML по зададената структура[cite: 4]."""
    root = ET.Element("STATEMENT")
    ET.SubElement(root, "IBAN_S").text = iban
    
    for t in trs:
        tran = ET.SubElement(root, "TRANSACTION")
        ET.SubElement(tran, "POST_DATE").text = t["post_date"]
        # AMOUNT_C за кредит, AMOUNT_D за дебит[cite: 4]
        tag = "AMOUNT_C" if t["type"] == "C" else "AMOUNT_D"
        ET.SubElement(tran, tag).text = t["amt"]
        
        ET.SubElement(tran, "TR_NAME").text = t["tr_name"]
        ET.SubElement(tran, "NAME_R").text = t["name"]
        ET.SubElement(tran, "REM_I").text = t["rem1"]
        ET.SubElement(tran, "REFERENCE").text = t["ref"]

    xml_str = ET.tostring(root, encoding="utf-8")
    return minidom.parseString(xml_str).toprettyxml(indent="  ")

def display_styled_table(trs):
    """Визуализация с цветово кодиране (Pandas 2.1+ съвместима)[cite: 1, 4]."""
    df_data = []
    for t in trs:
        prefix = "+" if t["type"] == "C" else "-"
        df_data.append({
            "ДАТА": t["post_date"],
            "ЧАС": "null",
            "ВИД": t["tr_name"],
            "НАРЕДИТЕЛ/ПОЛУЧАТЕЛ": t["name"],
            "ОСНОВАНИЕ": t["rem1"],
            "СУМА": f"{prefix}{t['amt']}",
            "ТИП": "Кредит" if t["type"] == "C" else "Дебит"
        })
    
    df = pd.DataFrame(df_data)

    def color_picker(val):
        """Зелено за приходи, червено за разходи[cite: 4]."""
        color = 'green' if '+' in str(val) else 'red' if '-' in str(val) else 'black'
        return f'color: {color}; font-weight: bold'

    # Използваме .map() за избягване на AttributeError в нови версии на Pandas[cite: 1, 4]
    try:
        styled_df = df.style.map(color_picker, subset=['СУМА'])
    except AttributeError:
        styled_df = df.style.applymap(color_picker, subset=['СУМА'])
        
    st.subheader("📊 Таблица с трансакции")
    st.dataframe(styled_df, use_container_width=True, hide_index=True)

# --- ГЛАВЕН ПОТОК ---
st.title("🏦 Конвертор на ОББ извлечения")

file = st.file_uploader("Качете PDF", type="pdf")

if file:
    with st.spinner('Обработка...'):
        text = ocr_pdf(file.read())
        iban, transactions = parse_obb_statement(text)
        
        if transactions:
            display_styled_table(transactions)
            
            xml_data = generate_xml(iban, transactions)
            
            st.divider()
            st.download_button(
                label="📥 Изтегли XML",
                data=xml_data,
                file_name=f"export_{iban}.xml",
                mime="text/xml"
            )
        else:
            st.error("Не са открити трансакции. Проверете документа.")
