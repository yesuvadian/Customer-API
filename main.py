from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer
from database import Base, engine
from middleware.auth_privilege import auth_and_privilege_middleware

# Routers
from routers import auth, categories, company_products, module, products, register, role, role_module_privileges, subcategories, token, totp, user_addresses, users
from routers import countries, states, company_tax_infos, company_tax_documents

# Create all database tables (optional, only if using auto-create)
# Base.metadata.create_all(bind=engine)

# Initialize FastAPI app
app = FastAPI(title="Vendor API")

# ----------------------------
# CORS configuration
# ----------------------------
origins = [
    "http://localhost:65469",  # frontend dev server
    "http://127.0.0.1:65469",
    # add more origins if needed
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ----------------------------
# Global middleware
# ----------------------------
app.middleware("http")(auth_and_privilege_middleware)
# Define the security scheme
security = HTTPBearer()

# ----------------------------
# Register routers
# ----------------------------
app.include_router(token.router)
app.include_router(users.router)
app.include_router(register.router)
app.include_router(totp.totp_router)

# Additional CRUD routers
app.include_router(countries.router)
app.include_router(states.router)
app.include_router(company_tax_infos.router)
app.include_router(company_tax_documents.router)
app.include_router(user_addresses.router)
app.include_router(categories.router)
app.include_router(subcategories.router)
app.include_router(products.router)
app.include_router(company_products.router)
app.include_router(auth.router)
app.include_router(module.router)
app.include_router(role.router)
app.include_router(role_module_privileges.router)

