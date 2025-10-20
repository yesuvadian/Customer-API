# create_tables.py
from database import Base, engine
import models  # make sure this imports all your model classes

# Create all tables in the public schema
Base.metadata.create_all(bind=engine)
print("Tables created successfully")
