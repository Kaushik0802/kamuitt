from sqlalchemy import create_engine
from models import Base, LocationUpdate, DriverProfile
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL")

# Create engine (MUST come before using it)
engine = create_engine(DATABASE_URL)

# Create all tables
Base.metadata.create_all(bind=engine)
print("Tables created")
