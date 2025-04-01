from sqlalchemy import Column, Integer, String
from sqlalchemy.ext.declarative import declarative_base

Base = declarative_base()

class Function(Base):
    __tablename__ = 'functions'
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, index=True)
    route = Column(String, unique=True, index=True)
    language = Column(String, index=True)
    timeout = Column(Integer)  # Timeout in seconds
