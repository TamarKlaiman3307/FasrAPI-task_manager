from sqlalchemy import Column, Integer, Text, Index
from db import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    name = Column(Text, nullable=False)
    email = Column(Text, nullable=False)
    password_hash = Column(Text, nullable=True)
    role = Column(Text, nullable=False, default="user")
    __table_args__ = (
        Index("users_email_unique", "email", unique=True),
    )