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
from io import BytesIO
import PyPDF2

from name_fixes import init_db, get_fixes, save_single_fix

# ---------------------------------------------------------
# CONFIG
# ---------------------------------------------------------
st.set_page_config(page_title="Statement Converter", layout="wide")
init_db()

# ---------------------------------------------------------
# DATE NORMALIZATION
# ---------------------------------------------------------
def normalize_date(date_str):
    date_str = date_str.replace(".", "/")
    for fmt in ("%d/%m/%Y", "%d/%m/%y"):
        try:
            d = datetime.strptime(date_str, fmt)
            return d.strftime("%d/%m/%Y")
        except:
            pass
    return date_str

# ---------------------------------------------------------
# OCR FOR SCANNED PDF
# ---------------------------------------------------------
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
        text = pytesseract.image_to_string(processed, lang="bul+eng", config="--oem 3 --psm 6")
        full_text += text + "\n"
    return full_text

# ---------------------------------------------------------
# APPLY FIXES
# ---------------------------------------------------------
def apply_fixes(text):
    fixes = get_fixes()
    for original, corrected in fixes:
        text = text.replace(original, corrected)
    return text

# ---------------------------------------------------------
# UNICREDIT NAME + REASON EXTRACTION
# ---------------------------------------------------------
def extract_name_and_reason(desc):
    clean = re.sub(r"\s+", " ", desc).strip()

    if "ATM" in clean:
        return "null", "ТЕГЛЕНЕ АТМ"

    m = re.search(r"Контрагент\s*:?\s*([A-ZА-Я0-9\s\.\-]+)", clean)
    if m:
        return m.group(1).strip(), clean

    m = re.search(r"Основание\s*:?\s*(.+)$", clean)
    if m:
        return "null", m.group(1).strip()

    return "null", clean

# ---------------------------------------------------------
# UNICREDIT PARSER (TEXT-BASED, STREAMLIT-CLOUD SAFE)
# ---------------------------------------------------------
import re
from pdfminer.high_level import extract_text
from io import BytesIO

def parse_unicredit_text(pdf_bytes):
    # 1) Извличаме истинския PDF текст (НЕ OCR)
    text = extract_text(BytesIO(pdf_bytes))

    # 2) Вземаме само частта след "Платежни операции"
    parts = re.split(r"Платежни операции", text, flags=re.I)
    if len(parts) < 2:
        return []

    table_text = parts[1]

    # 3) Намираме всички редове <tr>...</tr>
    rows = re.findall(r"<tr>(.*?)</tr>", table_text, flags=re.S)

    transactions = []
    pending = None  # за rowspan втори ред

    for row in rows:
        # Вземаме всички клетки <td>...</td>
        cells = re.findall(r"<td.*?>(.*?)</td>", row, flags=re.S)
        cells = [re.sub(r"\s+", " ", c).strip() for c in cells]

        # Пропускаме заглавни редове
        if len(cells) < 3:
            continue

        # Ако имаме втори ред от rowspan → добавяме към описанието
        if pending and len(cells) == 2:
            pending["description"] += " " + cells[0]
            transactions.append(pending)
            pending = None
            continue

        # Нормален ред или първи ред от rowspan
        if len(cells) >= 4:
            date_raw = cells[0]
            description = cells[1]
            type_raw = cells[2]
            eur_raw = cells[3]

            # Номер на транзакция (ако го има)
            tr_number = cells[5] if len(cells) >= 6 else ""

            # Нормализиране на дата
            m = re.match(r"(\d{2}\.\d{2}\.\d{4})", date_raw)
            if not m:
                continue

            post_date = m.group(1).replace(".", "/")

            # Тип
            tr_type = "D" if ("ДТ" in type_raw or "DT" in type_raw) else "C"

            # EUR
            eur = eur_raw.replace(",", ".").strip()

            tr = {
                "post_date": post_date,
                "description": description,
                "type": tr_type,
                "amt": eur,
                "number": tr_number
            }

            # Проверка за rowspan
            if "rowspan" in row:
                pending = tr
            else:
                transactions.append(tr)

    return transactions

# ---------------------------------------------------------
# OBB PARSER (unchanged)
# ---------------------------------------------------------
def parse_obb_statement(text):
    iban_match = re.search(r"IBAN\s*:\s*(BG\d{2}UBBS\d{14})", text)
    iban = iban_match.group(1) if iban_match else "Неизвестен"

    transactions = []
    lines = [l.strip() for l in text.split("\n") if l.strip()]

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
                "type": "C",
            }

            amt_match = re.search(r"(-?[\d\s,]+\.\d{2})\s*EUR", line.replace(",", ""))
            if amt_match:
                val_str = amt_match.group(1).replace(" ", "")
                val_float = float(val_str)
                tr["amt"] = f"{abs(val_float):.2f}"
                tr["type"] = "D" if val_float < 0 else "C"

            curr_j = i + 1
            extra_info = []
            while curr_j < len(lines) and not re.match(r"^\d{2}/\d{2}/\d{2}", lines[curr_j]):
                extra_info.append(lines[curr_j])
                curr_j += 1

            if len(extra_info) >= 1:
                tr["name"] = extra_info[0]
            if len(extra_info) >= 2:
                tr["rem1"] = extra_info[1]

            transactions.append(tr)
            i = curr_j - 1
        i += 1

    return iban, "Клиент", transactions

# ---------------------------------------------------------
# XML GENERATION
# ---------------------------------------------------------
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

# ---------------------------------------------------------
# UI
# ---------------------------------------------------------
st.title("🏦 Конвертор на банкови извлечения (ОББ + UniCredit)")

file = st.file_uploader("Качете PDF", type="pdf")

if file:
    with st.spinner("Обработка..."):
        pdf_bytes = file.read()

        # Extract text
        text = ocr_pdf(pdf_bytes)
        text = apply_fixes(text)
        st.text(text[:2000])

        # Detect bank
        if "UniCredit" in text or "УниКредит" in text:
            bank = "UniCredit"
            transactions = parse_unicredit_text(pdf_bytes)
            iban_match = re.search(r"IBAN:?(BG\d{20})", text)
            iban = iban_match.group(1) if iban_match else "Неизвестен"
            client_name = "Клиент"
        else:
            bank = "OBB"
            iban, client_name, transactions = parse_obb_statement(text)

        if transactions:
            df = pd.DataFrame(transactions)

            st.subheader("✏️ Редактирайте имена и основания")
            edited_df = st.data_editor(
                df[["post_date", "name", "rem1", "tr_name", "amt", "type"]],
                use_container_width=True,
                hide_index=True,
            )

            if st.button("💾 Запази всички корекции"):
                fixes = []
                for original, corrected in zip(df["name"], edited_df["name"]):
                    if original != corrected:
                        fixes.append([original, corrected])
                for original, corrected in zip(df["rem1"], edited_df["rem1"]):
                    if original != corrected:
                        fixes.append([original, corrected])

                for original, corrected in fixes:
                    save_single_fix(original, corrected)

                st.success("Корекциите са запазени!")
                transactions = edited_df.to_dict(orient="records")

            xml_data = generate_xml(iban, transactions)

            first_date = transactions[0]["post_date"]
            year = first_date[6:10]
            month = first_date[3:5]

            xml_filename = f"{bank}-{client_name}-{year}-{month}.xml"
            xml_filename = xml_filename.replace(" ", "_")

            st.download_button(
                label="📥 Изтегли XML",
                data=xml_data,
                file_name=xml_filename,
                mime="text/xml",
            )
        else:
            st.error("Не са открити трансакции.")
