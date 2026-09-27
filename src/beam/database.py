from sqlalchemy import create_engine, DateTime
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, Session
from datetime import datetime

engine = create_engine("sqlite:///beam.db", echo=True) 

class Base(DeclarativeBase):
    pass

class File(Base):
    __tablename__ = "files"

    file_id: Mapped[str] = mapped_column(primary_key=True)
    file_name: Mapped[str] 
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    




