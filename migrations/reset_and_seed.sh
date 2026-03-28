#!/bin/bash

# ============================================================
# RESET AND SEED DATABASE SCRIPT
# ============================================================
# Complete database reset with fresh seed data
# ============================================================

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${YELLOW}============================================================${NC}"
echo -e "${YELLOW}DATABASE RESET AND SEED SCRIPT${NC}"
echo -e "${YELLOW}============================================================${NC}"
echo ""
echo -e "${RED}WARNING: This will DELETE ALL DATA in the database!${NC}"
echo ""
read -p "Are you sure you want to continue? (yes/no): " confirm

if [ "$confirm" != "yes" ]; then
    echo "Operation cancelled."
    exit 0
fi

echo ""
echo -e "${YELLOW}Starting database reset...${NC}"
echo ""

# Database connection parameters (update these if needed)
DB_NAME="${DB_NAME:-cogniwatt_db}"
DB_USER="${DB_USER:-postgres}"
DB_HOST="${DB_HOST:-localhost}"
DB_PORT="${DB_PORT:-5432}"

# Check if psql is available
if ! command -v psql &> /dev/null; then
    echo -e "${RED}Error: psql command not found. Please install PostgreSQL client.${NC}"
    exit 1
fi

# Step 1: Drop all tables
echo -e "${GREEN}Step 1: Dropping all existing tables...${NC}"
psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" -f 000_drop_all_tables.sql
if [ $? -ne 0 ]; then
    echo -e "${RED}Error dropping tables. Exiting.${NC}"
    exit 1
fi
echo -e "${GREEN}✓ All tables dropped successfully${NC}"
echo ""

# Step 2: Run all migrations
echo -e "${GREEN}Step 2: Running all migrations...${NC}"
psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" -f run_all_migrations.sql
if [ $? -ne 0 ]; then
    echo -e "${RED}Error running migrations. Exiting.${NC}"
    exit 1
fi
echo -e "${GREEN}✓ All migrations completed successfully${NC}"
echo ""

# Step 3: Seed complete system
echo -e "${GREEN}Step 3: Seeding complete system...${NC}"
psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" -f seed_complete_system.sql
if [ $? -ne 0 ]; then
    echo -e "${RED}Error seeding database. Exiting.${NC}"
    exit 1
fi
echo -e "${GREEN}✓ System seeded successfully${NC}"
echo ""

echo -e "${GREEN}============================================================${NC}"
echo -e "${GREEN}DATABASE RESET AND SEED COMPLETED!${NC}"
echo -e "${GREEN}============================================================${NC}"
echo ""
echo -e "${YELLOW}Sample Login Credentials (password: admin123 for all):${NC}"
echo ""
echo "  Organization Admin: orgadmin@kptcl.com"
echo "  Department Head:    depthead@kptcl.com"
echo "  Tester 1:           tester1@kptcl.com"
echo "  Tester 2:           tester2@kptcl.com"
echo "  Engineer:           engineer@kptcl.com"
echo ""
echo -e "${GREEN}✓ Ready to test!${NC}"
echo ""
