import streamlit as st
import pytesseract
from pdf2image import convert_from_bytes
import cv2
import numpy as np
import re
import pandas as pd
import xml.etree.ElementTree as ET
from xml.dom import minidom
from datetime import datetime

from name_fixes import init_db, get_fixes, save_single_fix

# --- КОНФИГУРАЦИЯ ---
st.set_page_config(page_title="UBB Statement Converter", layout="wide")
init_db()

# --- НОРМАЛИЗАЦИЯ НА ДАТА ---
def normalize_date(date_str):
    for fmt in ("%d/%m/%Y", "%d/%m/%y"):
        try:
            d = datetime.strptime(date_str, fmt)
            return d.strftime("%d/%m/%Y")
        except:
            pass
    return date_str

# --- OCR ПРЕДОБРАБОТКА ---
def preprocess_image(img):
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    denoised = cv2.fastNlMeansDenoising(gray, None, 10, 7, 21)
    _, thresh = cv2.threshold(denoised, 180, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    return thresh

def ocr_pdf(pdf_bytes):
    pages = convert_from_bytes(pdf_bytes, dpi=400)
    full_text = ""
    for page in pages:
        img = np.array(page)
        processed = preprocess_image(img)
        text = pytesseract.image_to_string(processed, lang="bul+eng", config='--oem 3 --psm 6')
        full_text += text + "\n"
    return full_text

# --- ПРИЛАГАНЕ НА КОРЕКЦИИ ---
def apply_fixes(text):
    fixes = get_fixes()
    for original, corrected in fixes:
        text = text.replace(original, corrected)
    return text

# --- ПАРСЕР ---
def parse_obb_statement(text):
    iban_match = re.search(r"IBAN\s*:\s*(BG\d{2}UBBS\d{14})", text)
    iban = iban_match.group(1) if iban_match else "Неизвестен"

    transactions = []
    lines = [l.strip() for l in text.split('\n') if l.strip()]

    i = 0
    while i < len(lines):
        line = lines[i]
        date_match = re.match(r"^(\d{2}/\d{2}/\d{2,4})", line)

        if date_match:
            raw_date = date_match.group(1)
            fixed_date = normalize_date(raw_date)

            tr = {
                "post_date": fixed_date,
                "name": "null",
                "rem1": "null",
                "tr_name": "ОПЕРАЦИЯ",
                "amt": "0.00",
                "type": "C"
            }

            amt_match = re.search(r"(-?[\d\s,]+\.\d{2})\s*EUR", line.replace(",", ""))
            if amt_match:
                val_str = amt_match.group(1).replace(" ", "")
                val_float = float(val_str)
                tr["amt"] = f"{abs(val_float):.2f}"
                tr["type"] = "D" if val_float < 0 else "C"

            op_types = ["СЕПА ПОЛУЧЕН", "ИЗХОДЯЩ ПРЕВОД СЕПА", "МЕСЕЧНА ТАКСА", "ТЕГЛЕНЕ ОТ АТМ", "ПРЕВАЛУТИРАНЕ"]
            for op in op_types:
                if op in line.upper():
                    tr["tr_name"] = op
                    break

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

# --- XML ГЕНЕРАЦИЯ ---
def generate_xml(iban, trs):
    root = ET.Element("STATEMENT")
    ET.SubElement(root, "IBAN_S").text = iban

    for t in trs:
        tran = ET.SubElement(root, "TRANSACTION")
        ET.SubElement(tran, "POST_DATE").text = t["post_date"]
        tag = "AMOUNT_C" if t["type"] == "C" else "AMOUNT_D"
        ET.SubElement(tran, tag).text = t["amt"]
        ET.SubElement(tran, "TR_NAME").text = t["tr_name"]
        ET.SubElement(tran, "NAME_R").text = t["name"]
        ET.SubElement(tran, "REM_I").text = t["rem1"]

    xml_str = ET.tostring(root, encoding="utf-8")
    return minidom.parseString(xml_str).toprettyxml(indent="  ")

# --- UI ---
st.title("🏦 Конвертор на ОББ извлечения")

file = st.file_uploader("Качете PDF", type="pdf")

if file:
    with st.spinner("Обработка..."):
        text = ocr_pdf(file.read())
        text = apply_fixes(text)
        iban, transactions = parse_obb_statement(text)

        if transactions:
            df = pd.DataFrame(transactions)

            st.subheader("✏️ Редактирайте имена и основания")
            edited_df = st.data_editor(
                df[["post_date", "name", "rem1", "tr_name", "amt", "type"]],
                use_container_width=True,
                hide_index=True
            )

            if st.button("💾 Запази всички корекции"):
                fixes = []

                # сравняваме оригиналните и редактираните стойности
                for original, corrected in zip(df["name"], edited_df["name"]):
                    if original != corrected:
                        fixes.append([original, corrected])

                for original, corrected in zip(df["rem1"], edited_df["rem1"]):
                    if original != corrected:
                        fixes.append([original, corrected])

                # записваме всяка корекция поотделно
                for original, corrected in fixes:
                    save_single_fix(original, corrected)

                st.success("Корекциите са запазени!")

                transactions = edited_df.to_dict(orient="records")

            xml_data = generate_xml(iban, transactions)

            st.download_button(
                label="📥 Изтегли XML",
                data=xml_data,
                file_name=f"export_{iban}.xml",
                mime="text/xml"
            )
        else:
            st.error("Не са открити трансакции.")
