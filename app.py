import re
import xml.etree.ElementTree as ET
from datetime import datetime

# Нормализира OCR грешки
def normalize_text(t):
    replacements = {
        "СЕЛА": "СЕПА",
        "CENA": "СЕПА",
        "CEPA": "СЕПА",
        "NAP": "NAP",
        "MAP": "NAP",
        "HAP": "NAP",
        "EYP": "EUR",
        "EUK": "EUR",
        "EUP": "EUR",
        "BGN": "BGN",
        "ВСМ": "BGN",
        "ВОМ": "BGN",
        "ЕЦК": "EUR",
        "ЕПК": "EUR",
        "ET": "FT",   # OCR грешка в FT кодове
    }
    for wrong, right in replacements.items():
        t = t.replace(wrong, right)
    return t


# Намира IBAN
def extract_iban(text):
    m = re.search(r'BG\d{2}[A-Z0-9]{4}\d{14}', text)
    return m.group(0) if m else ""


# Намира период
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
        parts = d.split()
        return f"{parts[0]}/{months[parts[1]]}/{parts[2]}"
    return convert(m.group(1)), convert(m.group(2))


# Намира начално салдо
def extract_open_balance(text):
    m = re.search(r'Начално салдо:\s*([0-9\.,]+)\s*EUR', text)
    return m.group(1) if m else ""


# Намира крайно салдо
def extract_close_balance(text):
    m = re.search(r'Крайно салдо:\s*([0-9\.,]+)\s*EUR', text)
    return m.group(1) if m else ""


# Парсва транзакции
def extract_transactions(text):
    lines = text.split("\n")
    tx = []
    buffer = []

    for line in lines:
        if re.match(r"\d{2}/\d{2}/\d{2}", line.strip()):
            if buffer:
                tx.append("\n".join(buffer))
                buffer = []
        buffer.append(line)

    if buffer:
        tx.append("\n".join(buffer))

    parsed = []

    for block in tx:
        block = normalize_text(block)

        # Дата
        mdate = re.search(r"(\d{2}/\d{2}/\d{2})", block)
        if not mdate:
            continue
        d = mdate.group(1)
        d = f"{d[:2]}/{d[3:5]}/20{d[6:8]}"

        # FT/SBD/SBC код
        mref = re.search(r"(FT|SBD|SBC)[A-Z0-9\.\-]+", block)
        ref = mref.group(0) if mref else ""

        # Сума
        msum = re.search(r"([\-0-9\.,]+)\s*EUR", block)
        if not msum:
            continue
        amount = msum.group(1).replace(",", ".")

        # Тип: кредит или дебит
        if amount.startswith("-"):
            amount_d = amount[1:]
            amount_c = ""
        else:
            amount_d = ""
            amount_c = amount

        # TR_NAME (първите 40 символа от описанието)
        desc = block.replace("\n", " ")
        desc = re.sub(r"\s+", " ", desc)
        desc = desc.split(" ", 3)[-1]
        tr_name = desc[:40]

        # NAME_R (банка/контрагент)
        mname = re.search(r"OT BAHKA: ([A-Z0-9 \.\-]+)", block)
        name_r = mname.group(1).strip() if mname else ""

        # REM_I и REM_II
        rem_i = ""
        rem_ii = ""

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


# Генерира XML
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
