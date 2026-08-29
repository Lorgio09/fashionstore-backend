from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

# Reemplazarás esto con la URL de tu base de datos cuando esté en la nube
SQLALCHEMY_DATABASE_URL = "postgresql://usuario:password@localhost/fashionstore"

engine = create_engine(SQLALCHEMY_DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()