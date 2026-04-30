import re
import xml.etree.ElementTree as ET

# Нормализира OCR грешки
def normalize_text(t: str) -> str:
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
        "ЕЦК": "EUR",
        "ЕПК": "EUR",
        "ВСМ": "BGN",
        "ВОМ": "BGN",
        "ET": "FT",   # честа OCR грешка във FT кодове
    }
    for wrong, right in replacements.items():
        t = t.replace(wrong, right)
    return t


# Намира IBAN
def extract_iban(text: str) -> str:
    m = re.search(r'BG\d{2}[A-Z0-9]{4}\d{14}', text)
    return m.group(0) if m else ""


# Намира период
def extract_period(text: str):
    m = re.search(r'ОТ\s+(\d{2}\s+\S+\s+\d{4})\s+ДО\s+(\d{2}\s+\S+\s+\d{4})', text)
    if not m:
        return "", ""
    months = {
        "ЯНУ": "01", "ФЕВ": "02", "МАР": "03", "АПР": "04",
        "МАЙ": "05", "ЮНИ": "06", "ЮЛИ": "07", "АВГ": "08",
        "СЕП": "09", "ОКТ": "10", "НОЕ": "11", "ДЕК": "12"
    }

    def convert(d: str) -> str:
        parts = d.split()
        return f"{parts[0]}/{months.get(parts[1], '01')}/{parts[2]}"

    return convert(m.group(1)), convert(m.group(2))


# Намира начално салдо
def extract_open_balance(text: str) -> str:
    m = re.search(r'Начално салдо:\s*([0-9\.,]+)\s*EUR', text)
    return m.group(1) if m else ""


# Намира крайно салдо
def extract_close_balance(text: str) -> str:
    m = re.search(r'Крайно салдо:\s*([0-9\.,]+)\s*EUR', text)
    return m.group(1) if m else ""


# Парсва транзакции от целия текст на извлечението
def extract_transactions(text: str):
    text = normalize_text(text)
    lines = text.split("\n")
    tx_blocks = []
    buffer = []

    # групиране по блокове, започващи с дата
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
        block_norm = normalize_text(block)

        # Дата (POST_DATE)
        mdate = re.search(r"(\d{2}/\d{2}/\d{2})", block_norm)
        if not mdate:
            continue
        d = mdate.group(1)
        # 26 -> 2026
        d = f"{d[:2]}/{d[3:5]}/20{d[6:8]}"

        # FT/SBD/SBC код (REFERENCE)
        mref = re.search(r"\b(FT|SBD|SBC)[A-Z0-9\.\-]+", block_norm)
        ref = mref.group(0) if mref else ""

        # Сума в EUR (последната срещната сума в блока)
        msum_all = re.findall(r"([\-0-9\.,]+)\s*EUR", block_norm)
        if not msum_all:
            continue
        amount_raw = msum_all[-1].replace(" ", "")
        amount_raw = amount_raw.replace(",", ".")
        # Тип: кредит или дебит
        if amount_raw.startswith("-"):
            amount_d = amount_raw[1:]
            amount_c = ""
        else:
            amount_d = ""
            amount_c = amount_raw

        # Описание – TR_NAME: взимаме текста след референтния код до сумата
        desc_line = block_norm.replace("\n", " ")
        desc_line = re.sub(r"\s+", " ", desc_line)

        # опит да изрежем всичко до кода FT/SBD/SBC
        if mref:
            start = desc_line.find(ref) + len(ref)
            desc_part = desc_line[start:].strip()
        else:
            # fallback – след датата
            parts = desc_line.split(" ", 3)
            desc_part = parts[-1] if len(parts) == 4 else desc_line

        tr_name = desc_part[:40]

        # NAME_R – контрагент/банка
        mname = re.search(r"OT BAHKA: ([A-Z0-9 \.\-\(\)]+)", block_norm)
        name_r = mname.group(1).strip() if mname else ""

        # REM_I – често фактура/договор/номер
        mrem_i = re.search(r"(FAKTURA [^/]+|ФАКТУРА [^/]+|DOGOVOR [^/]+|ДОГОВОР [^/]+)", block_norm)
        rem_i = mrem_i.group(0).strip() if mrem_i else ""

        # REM_II – вторичен идентификатор, ако има
        mrem_ii = re.search(r"\b(INSTO/[A-Z0-9/]+|[A-Z0-9]{10,})\b", block_norm)
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


# Генерира XML по банковия формат (без TIME)
def build_xml(iban: str, from_date: str, till_date: str,
              open_balance: str, close_balance: str, transactions):
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


# Примерна „главна“ функция – подаваш й целия OCR текст от PDF
def pdf_text_to_xml(full_text: str) -> str:
    full_text = normalize_text(full_text)

    iban = extract_iban(full_text)
    from_date, till_date = extract_period(full_text)
    open_balance = extract_open_balance(full_text)
    close_balance = extract_close_balance(full_text)
    transactions = extract_transactions(full_text)

    return build_xml(iban, from_date, till_date, open_balance, close_balance, transactions)
