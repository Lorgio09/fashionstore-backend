import os
from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.ext.declarative import declarative_base

load_dotenv()

# 1. Intentamos leer la URL completa (Ideal para la nube/Render y para las pruebas)
SQLALCHEMY_DATABASE_URL = os.getenv("DATABASE_URL")

# 2. Si no existe (estamos en local), la armamos con las 5 variables
if not SQLALCHEMY_DATABASE_URL:
    USER = os.getenv("DB_USER")
    PASSWORD = os.getenv("DB_PASSWORD")
    HOST = os.getenv("DB_HOST")
    PORT = os.getenv("DB_PORT")
    DB = os.getenv("DB_NAME")
    SQLALCHEMY_DATABASE_URL = f"postgresql://{USER}:{PASSWORD}@{HOST}:{PORT}/{DB}"

_connect_args = {"check_same_thread": False} if SQLALCHEMY_DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args=_connect_args, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    """Una sesión por request. Es la ÚNICA función get_db: FastAPI la comparte entre la
    autenticación, el contexto de empresa y el endpoint dentro del mismo request."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
