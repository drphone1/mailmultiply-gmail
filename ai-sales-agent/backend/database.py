import os
from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    raise ValueError("DATABASE_URL environment variable not set. Please create a .env file with DATABASE_URL=postgresql://user:password@host:port/dbname")

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

def init_db():
    """
    Initializes the database by creating all tables defined in models.py.
    This function should be called once at application startup if tables don't exist.
    """
    # Import all modules here that define models so that
    # they are registered properly on the metadata. Otherwise
    # you will have to import them first before calling init_db()
    # Base.metadata.create_all(bind=engine) # This will be called after models are defined
    print("Database initialization function called. Tables will be created if models are imported and Base.metadata.create_all is run.")

def get_db():
    """
    Dependency for FastAPI routes to get a database session.
    Ensures the database session is always closed after the request.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# Example of how to create tables (typically called from main.py or a startup script)
# if __name__ == "__main__":
#     # This is just an example; actual table creation should happen
#     # after models are defined and imported.
#     print(f"Attempting to connect to database: {DATABASE_URL}")
#     # To create tables, you would import your models here and then run:
#     # import models # Assuming your SQLAlchemy models are in models.py
#     # models.Base.metadata.create_all(bind=engine)
#     # print("Tables should have been created if models were defined correctly.")
#     pass
