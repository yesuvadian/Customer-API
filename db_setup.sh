#!/bin/bash

# ---------------------------------
# Arguments
# ---------------------------------
ENVIRONMENT="dev"
CREATE_DB=false
DROP_TABLES=false
CREATE_TABLES=false
SEED=false
ALL=false

# Parse args
for arg in "$@"
do
    case $arg in
        --env=*)
        ENVIRONMENT="${arg#*=}"
        shift
        ;;
        --create-db)
        CREATE_DB=true
        shift
        ;;
        --drop-tables)
        DROP_TABLES=true
        shift
        ;;
        --create-tables)
        CREATE_TABLES=true
        shift
        ;;
        --seed)
        SEED=true
        shift
        ;;
        --all)
        ALL=true
        shift
        ;;
    esac
done

# ---------------------------------
# Server config
# ---------------------------------
if [ "$ENVIRONMENT" = "main" ]; then
    DB_NAME="Relu_Vendor2"
else
    DB_NAME="Relu_Vendor2"
fi

REMOTE_API_PATH="/apps/customer/api"
DB_USER="relu_user"

echo "====================================="
echo "Database Setup - $ENVIRONMENT"
echo "Database: $DB_NAME"
echo "====================================="

# If --all
if [ "$ALL" = true ]; then
    CREATE_DB=true
    DROP_TABLES=true
    CREATE_TABLES=true
    SEED=true
fi

# Show usage
if [ "$CREATE_DB" = false ] && [ "$CREATE_TABLES" = false ] && [ "$SEED" = false ] && [ "$DROP_TABLES" = false ]; then
    echo ""
    echo "Usage:"
    echo "  ./db_setup.sh --env=dev --all"
    echo "  ./db_setup.sh --env=dev --create-db"
    echo "  ./db_setup.sh --env=dev --drop-tables"
    echo "  ./db_setup.sh --env=dev --create-tables"
    echo "  ./db_setup.sh --env=dev --seed"
    echo ""
    exit 0
fi

# Production safety
if [ "$ENVIRONMENT" = "main" ]; then
    read -p "Run DB setup on PRODUCTION? (yes/no): " confirm
    if [ "$confirm" != "yes" ]; then
        echo "Cancelled."
        exit 1
    fi
fi

# ---------------------------------
# Step 1: Create Database
# ---------------------------------
if [ "$CREATE_DB" = true ]; then
    echo ""
    echo "Creating database '$DB_NAME'..."

    if sudo -u postgres psql -tAc "SELECT 1 FROM pg_database WHERE datname='$DB_NAME'" | grep -q 1; then
        echo "Database already exists"
    else
        sudo -u postgres psql -c "CREATE DATABASE \"$DB_NAME\" OWNER $DB_USER;"
        echo "Database created successfully"
    fi
fi

# ---------------------------------
# Step 2: Drop Tables
# ---------------------------------
if [ "$DROP_TABLES" = true ]; then
    echo ""

    if [ "$ENVIRONMENT" = "main" ]; then
        read -p "DROP ALL TABLES on PRODUCTION? (yes/no): " confirm
        if [ "$confirm" != "yes" ]; then
            echo "Cancelled."
            exit 1
        fi
    fi

    echo "Dropping all tables..."

    cd $REMOTE_API_PATH || exit 1
    source venv/bin/activate

    python - <<EOF
from database import engine
from sqlalchemy import text

with engine.connect() as conn:
    conn.execute(text('DROP SCHEMA public CASCADE'))
    conn.execute(text('CREATE SCHEMA public'))
    conn.execute(text('GRANT ALL ON SCHEMA public TO relu_user'))
    conn.commit()

print("All tables dropped successfully.")
EOF
fi

# ---------------------------------
# Step 3: Create Tables
# ---------------------------------
if [ "$CREATE_TABLES" = true ]; then
    echo ""
    echo "Creating / updating tables..."

    cd $REMOTE_API_PATH || exit 1
    source venv/bin/activate

    python - <<EOF
from database import engine
from models import Base
from sqlalchemy import inspect, text

Base.metadata.create_all(bind=engine)
print("Tables created/verified.")

inspector = inspect(engine)

with engine.connect() as conn:
    for table_name, table in Base.metadata.tables.items():
        schema = table.schema or 'public'
        try:
            existing = {c['name'] for c in inspector.get_columns(table_name, schema=schema)}
        except Exception:
            continue

        for col in table.columns:
            if col.name not in existing:
                col_type = col.type.compile(engine.dialect)
                default = ''

                if col.default is not None:
                    default = ' DEFAULT ' + str(col.default.arg)
                elif col.nullable:
                    default = ' DEFAULT NULL'

                stmt = f'ALTER TABLE {schema}.{table_name} ADD COLUMN {col.name} {col_type}{default}'
                print(f'Adding column: {schema}.{table_name}.{col.name}')
                conn.execute(text(stmt))

    conn.commit()

print("Migration complete.")
EOF
fi

# ---------------------------------
# Step 4: Seed
# ---------------------------------
if [ "$SEED" = true ]; then
    echo ""
    echo "Running seed..."

    cd $REMOTE_API_PATH || exit 1
    source venv/bin/activate
    python seed.py
fi

echo ""
echo "====================================="
echo "DB Setup Completed!"
echo "====================================="