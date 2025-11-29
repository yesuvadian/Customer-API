import pandas as pd
import re
import unicodedata
# Load original CSV file
df = pd.read_csv("product_firm_grouped_with_om.csv")

# --------------------------
# CLEANING FUNCTION
# --------------------------
def clean_text(t):
    if pd.isna(t):
        return ""
    # Normalize and remove weird chars
    t = unicodedata.normalize("NFKD", t)
    t = t.replace("â€“", "-").replace("–", "-")
    t = t.replace("  ", " ")
    return t.strip()


# --------------------------
# PHONE NUMBER EXTRACTION
# --------------------------
phone_regex = r'(\+?\d{2,3}[- ]?\d{6,12})'

def extract_phone(text):
    if pd.isna(text):
        return ""
    numbers = re.findall(phone_regex, text)
    return " / ".join(numbers) if numbers else ""


# --------------------------
# ADDRESS SPLITTING
# --------------------------
def split_address(addr):
    addr = clean_text(addr)

    # Remove phone numbers first
    addr_no_phone = re.sub(phone_regex, "", addr)

    # Extract PIN code (remove spaces inside: 560 091 → 560091)
    pin = ""
    pin_match = re.search(r'\b\d{3}\s?\d{3}\b', addr_no_phone)
    if pin_match:
        pin = pin_match.group().replace(" ", "")
        addr_no_phone = addr_no_phone.replace(pin_match.group(), "")

    # Remove words like "Ph:", "Mobile:", etc.
    addr_no_phone = re.sub(r'Ph:|Phone:|Mobile:', '', addr_no_phone, flags=re.IGNORECASE)

    # Split by comma
    parts = [p.strip().strip('.') for p in addr_no_phone.split(",") if p.strip()]

    # Defaults
    address_line1 = parts[0] if len(parts) > 0 else ""
    address_line2 = parts[1] if len(parts) > 1 else ""
    city = ""
    if len(parts) >= 3:
        city = parts[-1]
    elif len(parts) == 1 and "-" in parts[0]:     # for City-560091 only
        city = parts[0].split("-")[0].strip()

    state = ""   # optional: we can auto-detect later

    return pd.Series([address_line1, address_line2, city, state, pin])


# --------------------------
# APPLY TO DATAFRAME
# --------------------------
df["phonenumber"] = df["Firm Name & Address"].apply(extract_phone)

df[["address_line1", "address_line2", "city", "state", "postal_code"]] = \
    df["Firm Name & Address"].apply(split_address)

df.to_csv("output_address_split.csv", index=False)

print("File created: output_address_split.csv")