import streamlit as st
import pytesseract
from pdf2image import convert_from_path
import cv2
import numpy as np
import re
import xml.etree.ElementTree as ET
import tempfile
import shutil
import os

# -----------------------------
# OCR PREPROCESSING (златна среда)
# -----------------------------

def deskew(image):
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    coords = np.column_stack(np.where(gray < 255))
    if coords.size == 0:
        return image
    angle = cv2.minAreaRect(coords)[-1]
    angle = -(90 + angle) if angle < -45 else -angle
    (h, w) = image.shape[:2]
    M = cv2.getRotationMatrix2D((w // 2, h // 2), angle, 1.0)
    return cv2.warpAffine(image, M, (w, h),
                          flags=cv2.INTER_CUBIC,
                          borderMode=cv2.BORDER_REPLICATE)

def preprocess_moderate(pil_img):
    img = cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2BGR)
    img = deskew(img)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    gray = clahe.apply(gray)

    thresh = cv2.adaptiveThreshold(
        gray, 255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY,
        31, 5
    )

    denoised = cv2.fastNlMeansDenoising(thresh, h=15)
    return denoised

def ocr_text(image):
    return pytesseract.image_to_string(
        image,
        lang="bul+eng",
        config="--oem 1 --psm 4"
    )

# -----------------------------
# XML PARSER FUNCTIONS
# -----------------------------

def normalize_text(t):
    replacements = {
        "СЕЛА": "СЕПА",
        "CENA": "СЕПА",
        "CEPA": "СЕПА",
        "MAP": "NAP",
        "HAP": "NAP",
        "EYP": "EUR",
        "EUK": "EUR",
        "EUP": "EUR",
        "ВСМ": "BGN",
        "ВОМ": "BGN",
        "ЕЦК": "EUR",
        "ЕПК": "EUR",
        "ET": "FT",
    }
    for wrong, right in replacements.items():
        t = t.replace(wrong, right)
    return t

def extract_iban(text):
    m = re.search(r'BG\d{2}[A-Z0-9]{4}\d{14}', text)
    return m.group(0) if m else ""

def extract_period(text):
    m = re.search(r'ОТ\s+(\d{2}\s+\S+\s+\d{4})\s+ДО\s+(\d{2}\s+\S+\s+\d{4})', text)
    if not m:
        return "", ""
    months = {
        "ЯНУ": "01", "ФЕВ": "02", "МАР": "03", "АПР": "04",
        "МАЙ": "05", "ЮНИ": "06", "ЮЛИ": "07", "АВГ": "08",
        "СЕП": "09", "ОКТ": "10", "НОЕ": "11", "ДЕК": "12"
    }
    def convert(d):
        p = d.split()
        return f"{p[0]}/{months.get(p[1], '01')}/{p[2]}"
    return convert(m.group(1)), convert(m.group(2))

def extract_open_balance(text):
    m = re.search(r'Начално салдо:\s*([0-9\.,]+)\s*EUR', text)
    return m.group(1) if m else ""

def extract_close_balance(text):
    m = re.search(r'Крайно салдо:\s*([0-9\.,]+)\s*EUR', text)
    return m.group(1) if m else ""

def extract_transactions(text):
    text = normalize_text(text)
    lines = text.split("\n")
    tx_blocks = []
    buffer = []

    for line in lines:
        if re.match(r"\d{2}/\d{2}/\d{2}", line.strip()):
            if buffer:
                tx_blocks.append("\n".join(buffer))
                buffer = []
        buffer.append(line)
    if buffer:
        tx_blocks.append("\n".join(buffer))

    parsed = []

    for block in tx_blocks:
        block = normalize_text(block)

        mdate = re.search(r"(\d{2}/\d{2}/\d{2})", block)
        if not mdate:
            continue
        d = mdate.group(1)
        d = f"{d[:2]}/{d[3:5]}/20{d[6:8]}"

        mref = re.search(r"\b(FT|SBD|SBC)[A-Z0-9\.\-]+", block)
        ref = mref.group(0) if mref else ""

        msum_all = re.findall(r"([\-0-9\.,]+)\s*EUR", block)
        if not msum_all:
            continue
        amount_raw = msum_all[-1].replace(",", ".")
        if amount_raw.startswith("-"):
            amount_d = amount_raw[1:]
            amount_c = ""
        else:
            amount_d = ""
            amount_c = amount_raw

        desc_line = block.replace("\n", " ")
        desc_line = re.sub(r"\s+", " ", desc_line)
        if mref:
            start = desc_line.find(ref) + len(ref)
            desc_part = desc_line[start:].strip()
        else:
            parts = desc_line.split(" ", 3)
            desc_part = parts[-1] if len(parts) == 4 else desc_line
        tr_name = desc_part[:40]

        mname = re.search(r"OT BAHKA: ([A-Z0-9 \.\-\(\)]+)", block)
        name_r = mname.group(1).strip() if mname else ""

        mrem_i = re.search(r"(FAKTURA [^/]+|ФАКТУРА [^/]+|DOGOVOR [^/]+|ДОГОВОР [^/]+)", block)
        rem_i = mrem_i.group(0).strip() if mrem_i else ""

        mrem_ii = re.search(r"\b(INSTO/[A-Z0-9/]+|[A-Z0-9]{10,})\b", block)
        rem_ii = mrem_ii.group(0).strip() if mrem_ii else ""

        parsed.append({
            "date": d,
            "amount_d": amount_d,
            "amount_c": amount_c,
            "tr_name": tr_name,
            "name_r": name_r,
            "rem_i": rem_i,
            "rem_ii": rem_ii,
            "reference": ref
        })

    return parsed

def build_xml(iban, from_date, till_date, open_balance, close_balance, transactions):
    root = ET.Element("STATEMENT")

    ET.SubElement(root, "IBAN_S").text = iban
    ET.SubElement(root, "FROM_ST_DATE").text = from_date
    ET.SubElement(root, "TILL_ST_DATE").text = till_date
    ET.SubElement(root, "OPEN_BALANCE").text = open_balance

    for t in transactions:
        tx = ET.SubElement(root, "TRANSACTION")
        ET.SubElement(tx, "POST_DATE").text = t["date"]
        if t["amount_d"]:
            ET.SubElement(tx, "AMOUNT_D").text = t["amount_d"]
        if t["amount_c"]:
            ET.SubElement(tx, "AMOUNT_C").text = t["amount_c"]
        ET.SubElement(tx, "TR_NAME").text = t["tr_name"]
        ET.SubElement(tx, "NAME_R").text = t["name_r"]
        ET.SubElement(tx, "REM_I").text = t["rem_i"]
        ET.SubElement(tx, "REM_II").text = t["rem_ii"]
        ET.SubElement(tx, "REFERENCE").text = t["reference"]

    ET.SubElement(root, "CLOSE_BALANCE").text = close_balance

    return ET.tostring(root, encoding="utf-8").decode("utf-8")

# -----------------------------
# STREAMLIT UI
# -----------------------------

st.set_page_config(page_title="OCR → XML", layout="centered")
st.title("📄 OCR → XML Конвертор (ОББ)")

uploaded = st.file_uploader("Качи PDF извлечение", type=["pdf"])

if uploaded:
    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
        tmp.write(uploaded.read())
        pdf_path = tmp.name

    st.info("Обработване на PDF…")

    images = convert_from_path(pdf_path, dpi=400)

    full_text = ""
    for img in images:
        processed = preprocess_moderate(img)
        full_text += ocr_text(processed) + "\n\n"

    full_text = normalize_text(full_text)

    iban = extract_iban(full_text)
    from_date, till_date = extract_period(full_text)
    open_balance = extract_open_balance(full_text)
    close_balance = extract_close_balance(full_text)
    transactions = extract_transactions(full_text)

    xml_output = build_xml(iban, from_date, till_date, open_balance, close_balance, transactions)

    st.subheader("XML резултат:")
    st.text_area("", xml_output, height=400)

    st.download_button("📥 Изтегли XML", xml_output, "statement.xml")
