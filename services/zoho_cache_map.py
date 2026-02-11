# services/zoho_cache_map.py

ZOHO_MODULE_CACHE_KEYS = {
    # -------------------------
    # Customer-scoped modules
    # -------------------------
    "quotes": ["dashboard", "quotes"],
    "quote": ["dashboard", "quotes"],
    "estimates": ["dashboard", "quotes"],

    "invoices": ["dashboard", "invoices"],
    "invoice": ["dashboard", "invoices"],

    "salesorders": ["dashboard", "salesorders"],
    "salesorder": ["dashboard", "salesorders"],
    "sales_order": ["dashboard", "salesorders"],

    "payments": ["dashboard", "payments"],
    "payment": ["dashboard", "payments"],
    "customerpayments": ["dashboard", "payments"],
    "paymentsreceived": ["dashboard", "payments"],

    "retainerinvoices": ["dashboard", "retainers"],
    "retainerinvoice": ["dashboard", "retainers"],

    # -------------------------
    # Global (NO contact_id)
    # -------------------------
    "items": ["items"],
    "item": ["items"],
    "taxes": ["taxes"],
}
