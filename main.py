from fastapi import FastAPI
from database import Base, engine
from routers import register, token, totp, users
from middleware.auth_privilege import auth_and_privilege_middleware
from fastapi.middleware.cors import CORSMiddleware
# Create all database tables
#Base.metadata.create_all(bind=engine)

# Initialize app
app = FastAPI(title="Vendor API")


origins = [
    "http://localhost:3000",  # frontend dev server
    "http://127.0.0.1:3000",
    # add more origins if needed
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Add global middleware
app.middleware("http")(auth_and_privilege_middleware)

# Register routers
app.include_router(token.router)
app.include_router(users.router)
app.include_router(register.router)
app.include_router(totp.totp_router)

