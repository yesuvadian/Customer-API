# services/zoho_cache_map.py

# services/zoho_cache_map.py

ZOHO_MODULE_CACHE_KEYS = {
    # Customer-scoped
    "quotes": ["dashboard", "quotes"],
    "estimates": ["dashboard", "quotes"],

    "invoices": ["dashboard", "invoices"],
    "invoice": ["dashboard", "invoices"],

    "salesorders": ["dashboard", "salesorders"],
    "sales_order": ["dashboard", "salesorders"],

    "customerpayments": ["dashboard", "payments"],
    "paymentsreceived": ["dashboard", "payments"],

    "retainerinvoices": ["dashboard", "retainers"],

    # Global (NO contact_id)
    "items": ["items"],
    "item": ["items"],
    "taxes": ["taxes"],
}

