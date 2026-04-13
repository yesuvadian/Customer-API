#!/bin/bash

# Reset Database and Run Seed Script
# This script drops all tables, recreates schema, runs migrations, and seeds data

# Colors for output
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Database configuration
DB_NAME="database_name"  # Change this to your database name
DB_USER="postgres"
DB_HOST="localhost"
DB_PORT="5432"

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}  Database Reset & Seed Script${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

# Ask for confirmation
echo -e "${YELLOW}⚠️  WARNING: This will DROP ALL TABLES in database '${DB_NAME}'${NC}"
echo -e "${YELLOW}Are you sure you want to continue? (yes/no)${NC}"
read -r confirmation

if [ "$confirmation" != "yes" ]; then
    echo -e "${RED}❌ Aborted${NC}"
    exit 1
fi

echo ""
echo -e "${GREEN}Step 1: Dropping all tables in public schema...${NC}"

# Drop all tables in public schema
psql -U "$DB_USER" -d "$DB_NAME" -h "$DB_HOST" -p "$DB_PORT" <<EOF
BEGIN;
DROP SCHEMA IF EXISTS public CASCADE;
CREATE SCHEMA public;
GRANT ALL ON SCHEMA public TO $DB_USER;
GRANT ALL ON SCHEMA public TO public;
COMMIT;
EOF

if [ $? -eq 0 ]; then
    echo -e "${GREEN}✓ All tables dropped successfully${NC}"
else
    echo -e "${RED}✗ Failed to drop tables${NC}"
    exit 1
fi

echo ""
echo -e "${GREEN}Step 2: Running migrations...${NC}"

# Run migration 003 (multi-session testing)
echo -e "${BLUE}  - Running migration 003_add_multi_session_testing.sql${NC}"
psql -U "$DB_USER" -d "$DB_NAME" -h "$DB_HOST" -p "$DB_PORT" -f migrations/003_add_multi_session_testing.sql

if [ $? -eq 0 ]; then
    echo -e "${GREEN}  ✓ Migration 003 completed${NC}"
else
    echo -e "${RED}  ✗ Migration 003 failed${NC}"
    exit 1
fi

# Run migration 004 (session comments)
echo -e "${BLUE}  - Running migration 004_add_session_comments.sql${NC}"
psql -U "$DB_USER" -d "$DB_NAME" -h "$DB_HOST" -p "$DB_PORT" -f migrations/004_add_session_comments.sql

if [ $? -eq 0 ]; then
    echo -e "${GREEN}  ✓ Migration 004 completed${NC}"
else
    echo -e "${RED}  ✗ Migration 004 failed${NC}"
    exit 1
fi

echo ""
echo -e "${GREEN}Step 3: Creating tables via SQLAlchemy...${NC}"

# Run Python script to create tables
python3 <<EOF
from database import Base, engine
from models import *

try:
    Base.metadata.create_all(bind=engine)
    print("${GREEN}✓ Tables created successfully${NC}")
except Exception as e:
    print(f"${RED}✗ Failed to create tables: {e}${NC}")
    exit(1)
EOF

if [ $? -eq 0 ]; then
    echo -e "${GREEN}✓ SQLAlchemy tables created${NC}"
else
    echo -e "${RED}✗ Failed to create SQLAlchemy tables${NC}"
    exit 1
fi

echo ""
echo -e "${GREEN}Step 4: Running seed script...${NC}"

# Check if seed.py exists
if [ ! -f "seed.py" ]; then
    echo -e "${RED}✗ seed.py not found${NC}"
    exit 1
fi

# Run seed script
python3 seed.py

if [ $? -eq 0 ]; then
    echo -e "${GREEN}✓ Seed data loaded successfully${NC}"
else
    echo -e "${RED}✗ Failed to load seed data${NC}"
    exit 1
fi

echo ""
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}✓ Database reset and seed completed!${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""
echo -e "${BLUE}Next steps:${NC}"
echo -e "  1. Start the backend server: ${YELLOW}uvicorn main:app --reload${NC}"
echo -e "  2. Run the test script: ${YELLOW}python3 test_multi_session_complete.py${NC}"
echo ""
