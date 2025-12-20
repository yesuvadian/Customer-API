from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer
from database import Base, engine
from middleware.auth_privilege import auth_and_privilege_middleware
from routers.file_download import router as file_download_router



# Routers
from routers import (
    auth,
    bank_document,
    bank_info,
    categories,
    company_product_certificates,
    company_product_supply_references,
    company_products,
    contacts,
    dashboard,
    divisions,
    erp_router,
    invoices,
    module,
    mongo_router,
    payments,
    plan,
    products,
    quotes,
    register,
    retainerinvoices,
    role,
    role_module_privileges,
    sales_orders,
    subcategories,
    sync_full_erp,
    token,
    totp,
    user_addresses,
    userdocument,
    userrole,
    users,
    countries,
    states,
    company_tax_infos,
    company_tax_documents,
    category_master,
    category_details,
    cities,
    zoho_auth,
    zoho_items
)
from routers.kyc_router import router as kyc_router

# Optional: create all database tables (uncomment if needed)
# Base.metadata.create_all(bind=engine)

# Initialize FastAPI app
app = FastAPI(title="Vendor API")

# ----------------------------
# CORS configuration
# ----------------------------
origins = [
    "http://localhost:65469",
    "http://127.0.0.1:65469",
    # Add your production frontends here
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # For testing; restrict to origins in production
    allow_credentials=True,
    allow_methods=["*"],  # Crucial: allows GET, POST, PUT, DELETE
    allow_headers=["*"],  # Allows Authorization header for JWT
)

# ----------------------------
# Global middleware
# ----------------------------
# This must come after app initialization but before routers
app.middleware("http")(auth_and_privilege_middleware)

# Security scheme (optional)
security = HTTPBearer()

# ----------------------------
# Register routers
# ----------------------------

# Authentication & Token
app.include_router(token.router)
app.include_router(auth.router)
app.include_router(register.router)
app.include_router(totp.totp_router)

# User & Roles
app.include_router(users.router)
app.include_router(userrole.user_role_router)
app.include_router(role.router)
app.include_router(role_module_privileges.router)

# Master Data & Categories
app.include_router(categories.router)
app.include_router(subcategories.router)
app.include_router(category_master.router)
app.include_router(category_details.router)
app.include_router(products.router)
app.include_router(company_products.router)

# Company & Finance
app.include_router(company_tax_infos.router)
app.include_router(company_tax_documents.router)
app.include_router(bank_document.router)
app.include_router(bank_info.router)
app.include_router(company_product_certificates.router)
app.include_router(company_product_supply_references.router)

# Location & Divisions
app.include_router(divisions.router)
app.include_router(user_addresses.router)
app.include_router(countries.router)
app.include_router(states.router)
app.include_router(cities.router)

# Dashboard, Module & Plan
app.include_router(dashboard.router)
app.include_router(module.router)
app.include_router(plan.router)

# User documents
app.include_router(userdocument.router)

# ERP Sync
app.include_router(sync_full_erp.router)

# KYC
app.include_router(kyc_router)

app.include_router(file_download_router)
app.include_router(erp_router.router)
app.include_router(mongo_router.router)
app.include_router(quotes.router)
app.include_router(zoho_items.router)
app.include_router(zoho_auth.router)
app.include_router(invoices.router)
app.include_router(payments.router)
app.include_router(contacts.router)
app.include_router(retainerinvoices.router)
app.include_router(products.router)
app.include_router(sales_orders.router)


# Optional: enable auto-create database tables at startup
# @app.on_event("startup")
# async def startup_event():
#     Base.metadata.create_all(bind=engine)
