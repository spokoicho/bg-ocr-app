import streamlit as st
import pytesseract
from pdf2image import convert_from_bytes
import cv2
import numpy as np
import re
import xml.etree.ElementTree as ET

# ---------------------------------------------------------
# OCR PREPROCESSING
# ---------------------------------------------------------

def clean_text(text):
    text = ''.join(ch for ch in text if 32 <= ord(ch) <= 126 or ch in
                   "абвгдежзийклмнопрстуфхцчшщъьюяАБВГДЕЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЬЮЯ .,:;/()-0123456789")
    text = re.sub(r'[\x00-\x1F\x7F]', '', text)
    return text

def preprocess_image(img):
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    coords = np.column_stack(np.where(gray < 255))
    if len(coords) > 0:
        angle = cv2.minAreaRect(coords)[-1]
        if angle < -45:
            angle = -(90 + angle)
        else:
            angle = -angle
        (h, w) = gray.shape[:2]
        M = cv2.getRotationMatrix2D((w//2, h//2), angle, 1.0)
        gray = cv2.warpAffine(gray, M, (w, h), flags=cv2.INTER_CUBIC)

    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8,8))
    gray = clahe.apply(gray)

    th = cv2.adaptiveThreshold(gray,255,cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                               cv2.THRESH_BINARY,31,15)

    kernel = np.ones((2,2), np.uint8)
    th = cv2.morphologyEx(th, cv2.MORPH_CLOSE, kernel)

    th = cv2.fastNlMeansDenoising(th, None, 30, 7, 21)

    return th

def ocr_pdf(pdf_bytes):
    pages = convert_from_bytes(pdf_bytes, dpi=400)
    full_text = ""

    for page in pages:
        img = np.array(page)
        processed = preprocess_image(img)
        text = pytesseract.image_to_string(processed, lang="bul+eng", config="--oem 1 --psm 6")
        full_text += "\n" + text

    return clean_text(full_text)

# ---------------------------------------------------------
# VISUAL OCR FORMATTER
# ---------------------------------------------------------

def pretty_blocks(text):
    text = re.sub(r"(?<!\d)(\d{2}/\d{2}/\d{2,4})", r"\n\1", text)
    text = re.sub(r"(FT[0-9A-Z]+)", r"\n\1", text)
    text = re.sub(r"(SBD\.[0-9A-Z\-]+)", r"\n\1", text)
    text = re.sub(r"(SBC\.[0-9A-Z\-]+)", r"\n\1", text)
    text = re.sub(r"(ATM)", r"\nATM", text)
    text = re.sub(r"([0-9.,]+\s*EUR)", r"\n\1", text)
    text = re.sub(r"([0-9.,]+\s*BGN)", r"\n\1", text)

    lines = [l.strip() for l in text.split("\n") if l.strip()]

    blocks = []
    current = []

    for l in lines:
        if re.match(r"^\d{2}/\d{2}/\d{2,4}", l) and current:
            blocks.append(current)
            current = []
        current.append(l)

    if current:
        blocks.append(current)

    formatted = ""
    for b in blocks:
        formatted += "### 🟦 Операция\n"
        for line in b:
            if re.match(r"^\d{2}/\d{2}/\d{2,4}", line):
                formatted += f"**Дата:** {line}\n"
            elif line.startswith(("FT", "SBD", "SBC")):
                formatted += f"**Код:** `{line}`\n"
            elif "EUR" in line:
                formatted += f"**Сума:** {line}\n"
            else:
                formatted += f"{line}\n"
        formatted += "\n---\n\n"

    return formatted

# ---------------------------------------------------------
# PARSER HELPERS
# ---------------------------------------------------------

def normalize_amount(val):
    if not val:
        return ""
    val = val.replace(" ", "").replace(",", ".")
    parts = val.split(".")
    if len(parts) > 2:
        val = "".join(parts[:-1]) + "." + parts[-1]
    return val

def normalize_date(d):
    m = re.match(r"(\d{2})/(\d{2})/(\d{2,4})", d)
    if not m:
        return d
    dd, mm, yy = m.groups()
    if len(yy) == 2:
        yy = "20" + yy
    return f"{dd}/{mm}/{yy}"

def is_outgoing(block, amount):
    b = block.upper()
    if "-" in amount:
        return True
    if "ТЕГЛЕНЕ" in b or "ATM" in b:
        return True
    if "ИЗХОДЯЩ" in b:
        return True
    if "FT" in b and "ПОЛУЧЕН" not in b:
        return True
    return False

def detect_type(block, outgoing):
    b = block.upper()
    if "SBD" in b and not outgoing:
        return "СЕПА ПОЛУЧЕН"
    if "SBC" in b or ("SBD" in b and outgoing):
        return "СЕПА ИЗХОДЯЩ"
    if "ТЕГЛЕНЕ" in b or "ATM" in b:
        return "ATM ТЕГЛЕНЕ"
    if "TAKSA" in b or "ТАКСА" in b:
        return "ТАКСА ОБСЛУЖВАНЕ"
    return "ПРЕВОД"

def extract_reference(block):
    m = re.search(r"(FT[0-9A-Z]+|SBD\.[0-9A-Z\-]+|SBC\.[0-9A-Z\-]+|8002[0-9A-Z\-]+)", block)
    return m.group(1) if m else ""

def extract_name_r(lines, idx):
    for i in range(idx+1, len(lines)):
        t = lines[i].strip()
        if any(x in t for x in ["EUR", "BGN"]):
            continue
        if re.match(r"\d{2}/\d{2}/\d{2,4}", t):
            continue
        if re.match(r"(FT|SBD|SBC)\.", t):
            continue
        if "OT BANKA" in t.upper():
            continue
        if "ПОЛУЧЕН" in t.upper() or "ПРЕВОД" in t.upper():
            continue
        if len(t.split()) <= 6:
            return t
    return ""

def extract_rem_i(lines, idx, name_r):
    start = False
    for i in range(idx+1, len(lines)):
        t = lines[i].strip()
        if t == name_r:
            start = True
            continue
        if start:
            if any(k in t.upper() for k in ["ФАКТ", "FAKT", "ДОКУМ", "DOC", "УСЛУГ", "TRANSFER", "НОМЕР"]):
                return t
    return ""

def extract_rem_ii(block):
    m = re.findall(r"\b[0-9A-Z]{10,30}\b", block)
    if m:
        return m[-1]
    return ""

# ---------------------------------------------------------
# MAIN PARSER
# ---------------------------------------------------------

def parse_statement(text):

    text = re.sub(r"(?<!\d)(\d{2}/\d{2}/\d{2,4})", r"\n\1", text)

    lines = [l for l in text.split("\n") if l.strip()]

    m = re.search(r"ОТ\s+(\d{2}\s*[А-ЯA-Z]+\s*\d{4}).*ДО\s+(\d{2}\s*[А-ЯA-Z]+\s*\d{4})", text)
    from_date = ""
    till_date = ""
    if m:
        months = {
            "ЯНУ": "01", "ФЕВ": "02", "МАР": "03", "АПР": "04", "МАЙ": "05",
            "ЮНИ": "06", "ЮЛИ": "07", "АВГ": "08", "СЕП": "09", "ОКТ": "10",
            "НОЕ": "11", "ДЕК": "12"
        }
        fd = m.group(1)
        td = m.group(2)
        def conv(d):
            parts = d.split()
            dd = parts[0]
            mm = months.get(parts[1][:3].upper(), "01")
            yy = parts[2]
            return f"{dd}/{mm}/{yy}"
        from_date = conv(fd)
        till_date = conv(td)

    m2 = re.search(r"Начално салдо[: ]+([0-9.,]+)", text)
    open_balance = normalize_amount(m2.group(1)) if m2 else ""

    m3 = re.search(r"Крайно салдо[: ]+([0-9.,]+)", text)
    close_balance = normalize_amount(m3.group(1)) if m3 else ""

    transactions = []
    for i, line in enumerate(lines):

        if re.match(r"^\d{2}/\d{2}/\d{2,4}", line):

            block = line
            j = i + 1
            while j < len(lines) and not re.match(r"^\d{2}/\d{2}/\d{2,4}", lines[j]):
                block += "\n" + lines[j]
                j += 1

            date = normalize_date(re.match(r"(\d{2}/\d{2}/\d{2,4})", line).group(1))

            amt_m = re.search(r"([\-]?[0-9.,]+)\s*EUR", block)
            amount = normalize_amount(amt_m.group(1)) if amt_m else ""

            outgoing = is_outgoing(block, amount)
            tr_type = detect_type(block, outgoing)

            reference = extract_reference(block)
            name_r = extract_name_r(lines, i)
            rem_i = extract_rem_i(lines, i, name_r)
            rem_ii = extract_rem_ii(block)

            transactions.append({
                "date": date,
                "amount": amount,
                "type": tr_type,
                "name_r": name_r,
                "rem_i": rem_i,
                "rem_ii": rem_ii,
                "reference": reference,
                "outgoing": outgoing
            })

    return from_date, till_date, open_balance, close_balance, transactions

# Визуален преглед на транзакциите
st.subheader("Визуален преглед на транзакциите")

import pandas as pd

table_rows = []
for t in trs:
    row = {
        "Дата": t["date"],
        "Час": "",
        "Вид": t["type"],
        "Наредител/Получател": t["name_r"],
        "Основание": t["rem_i"],
        "Сума": t["amount"],
        "Тип": "Кредит" if not t["outgoing"] else "Дебит"
    }
    table_rows.append(row)

df = pd.DataFrame(table_rows)

# Подравняване и стил
st.dataframe(
    df.style.format({
        "Сума": lambda x: f"{x} EUR"
    }).apply(
        lambda row: ["color: green" if row["Тип"] == "Кредит" else "color: red"] * len(row),
        axis=1
    ),
    use_container_width=True
)

# ---------------------------------------------------------
# XML GENERATOR
# ---------------------------------------------------------

def generate_xml(iban, from_date, till_date, open_balance, close_balance, transactions):
    root = ET.Element("STATEMENT")

    ET.SubElement(root, "IBAN_S").text = iban
    ET.SubElement(root, "FROM_ST_DATE").text = from_date
    ET.SubElement(root, "TILL_ST_DATE").text = till_date
    ET.SubElement(root, "OPEN_BALANCE").text = open_balance

    for t in transactions:
        tr = ET.SubElement(root, "TRANSACTION")
        ET.SubElement(tr, "POST_DATE").text = t["date"]

        if t["outgoing"]:
            ET.SubElement(tr, "AMOUNT_D").text = t["amount"]
        else:
            ET.SubElement(tr, "AMOUNT_C").text = t["amount"]

        ET.SubElement(tr, "TR_NAME").text = t["type"]
        ET.SubElement(tr, "NAME_R").text = t["name_r"]
        ET.SubElement(tr, "REM_I").text = t["rem_i"]
        ET.SubElement(tr, "REM_II").text = t["rem_ii"]
        ET.SubElement(tr, "REFERENCE").text = t["reference"]

    ET.SubElement(root, "CLOSE_BALANCE").text = close_balance

    xml_str = ET.tostring(root, encoding="utf-8").decode("utf-8")
    xml_str = xml_str.replace("><", ">\n<")
    return xml_str

# ---------------------------------------------------------
# STREAMLIT UI
# ---------------------------------------------------------

st.title("PDF → XML (ОББ формат)")

uploaded = st.file_uploader("Качи PDF", type=["pdf"])

if uploaded:
    text = ocr_pdf(uploaded.read())

    pretty = pretty_blocks(text)
    st.markdown(pretty)

    iban = st.text_input("IBAN", "BG00XXXX00000000000000")

    if st.button("Генерирай XML"):
        from_d, till_d, open_b, close_b, trs = parse_statement(text)
        xml_output = generate_xml(iban, from_d, till_d, open_b, close_b, trs)

        st.code(xml_output, language="xml")

        st.download_button(
            "Свали XML",
            data=xml_output.encode("utf-8"),
            file_name="statement.xml",
            mime="application/xml"
        )
