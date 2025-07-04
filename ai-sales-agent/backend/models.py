from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Text, Boolean, Enum as SQLAlchemyEnum
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func # For server-side default timestamps
from pydantic import BaseModel, EmailStr, Field, validator # For Pydantic schemas
from typing import Optional, List
import enum # For Python enums to be used with SQLAlchemyEnum

from .database import Base # Import Base from database.py

# Enum for message direction
class MessageDirection(str, enum.Enum):
    INBOUND = "inbound"
    OUTBOUND = "outbound"

# --- SQLAlchemy Models ---

class Contact(Base):
    __tablename__ = "contacts"

    id = Column(Integer, primary_key=True, index=True)
    phone_number = Column(String, unique=True, index=True, nullable=False)
    name_from_vcf = Column(String, nullable=True) # Name from uploaded VCF/CSV
    extracted_name = Column(String, nullable=True) # Name extracted by LLM/parsing
    profile_picture_url = Column(String, nullable=True)
    email = Column(String, nullable=True, index=True)
    company = Column(String, nullable=True)
    address = Column(String, nullable=True)
    notes = Column(Text, nullable=True)
    # Placeholder for linking to analysis results, assuming a one-to-one or one-to-many
    # analysis_results_id = Column(Integer, ForeignKey("analysis_results.id"), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    conversations = relationship("Conversation", back_populates="contact")
    # analysis_results = relationship("AnalysisResult", back_populates="contact")
    groups = relationship("ContactGroupMember", back_populates="contact")


class WhatsAppAccount(Base):
    __tablename__ = "whatsapp_accounts"

    id = Column(Integer, primary_key=True, index=True)
    account_name = Column(String, unique=True, nullable=False) # e.g., "My Main Business Line"
    phone_number_id = Column(String, unique=True, nullable=False) # Provided by WhatsApp API provider
    access_token = Column(String, nullable=False) # API Access Token
    is_default = Column(Boolean, default=False) # To mark one account as default for sending/webhook

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    conversations = relationship("Conversation", back_populates="whatsapp_account")


class Conversation(Base):
    __tablename__ = "conversations"

    id = Column(Integer, primary_key=True, index=True)
    contact_id = Column(Integer, ForeignKey("contacts.id"), nullable=False)
    whatsapp_account_id = Column(Integer, ForeignKey("whatsapp_accounts.id"), nullable=False) # Which of our accounts handled this

    message_id_whatsapp = Column(String, unique=True, index=True, nullable=True) # Message ID from WhatsApp
    sender_phone = Column(String, index=True) # Actual sender (could be contact or our WA account)
    receiver_phone = Column(String, index=True) # Actual receiver (could be contact or our WA account)
    message_text = Column(Text, nullable=True)
    timestamp = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    direction = Column(SQLAlchemyEnum(MessageDirection), nullable=False)
    status = Column(String, nullable=True) # e.g., "sent", "delivered", "read", "failed"

    contact = relationship("Contact", back_populates="conversations")
    whatsapp_account = relationship("WhatsAppAccount", back_populates="conversations")

class ContactGroup(Base):
    __tablename__ = "contact_groups"

    id = Column(Integer, primary_key=True, index=True)
    group_name = Column(String, unique=True, nullable=False) # Name of the WhatsApp group scraped
    scraped_on = Column(DateTime(timezone=True), server_default=func.now())
    description = Column(Text, nullable=True)

    members = relationship("ContactGroupMember", back_populates="group")

class ContactGroupMember(Base):
    __tablename__ = "contact_group_members"

    contact_id = Column(Integer, ForeignKey("contacts.id"), primary_key=True)
    group_id = Column(Integer, ForeignKey("contact_groups.id"), primary_key=True)

    contact = relationship("Contact", back_populates="groups")
    group = relationship("ContactGroup", back_populates="members")


# --- Pydantic Schemas (for API request/response validation) ---

# Base schemas (common fields, used for creation and reading)
class ContactBase(BaseModel):
    phone_number: str = Field(..., example="1234567890")
    name_from_vcf: Optional[str] = None
    extracted_name: Optional[str] = None
    profile_picture_url: Optional[str] = None
    email: Optional[EmailStr] = None
    company: Optional[str] = None
    address: Optional[str] = None
    notes: Optional[str] = None

class ContactCreate(ContactBase):
    pass # Inherits all from ContactBase, can add more if needed for creation

class ContactResponse(ContactBase):
    id: int
    created_at: Optional[datetime] = None # Using datetime from stdlib for Pydantic
    updated_at: Optional[datetime] = None

    class Config:
        orm_mode = True # Allows Pydantic to work with ORM objects

class WhatsAppAccountBase(BaseModel):
    account_name: str = Field(..., example="Main Business Line")
    phone_number_id: str = Field(..., example="123456789012345")
    access_token: str = Field(..., example="EAA...")
    is_default: Optional[bool] = False

class WhatsAppAccountCreate(WhatsAppAccountBase):
    pass

class WhatsAppAccountResponse(WhatsAppAccountBase):
    id: int
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        orm_mode = True


class ConversationBase(BaseModel):
    message_id_whatsapp: Optional[str] = None
    sender_phone: str
    receiver_phone: str
    message_text: Optional[str] = None
    direction: MessageDirection
    status: Optional[str] = None
    timestamp: Optional[datetime] = None # Allow client to set or default to now()

class ConversationCreate(ConversationBase):
    contact_phone_number: str # To identify/create contact
    whatsapp_account_phone_id: str # To identify which of our accounts

class ConversationResponse(ConversationBase):
    id: int
    contact_id: int
    whatsapp_account_id: int
    # timestamp will be included from ConversationBase

    class Config:
        orm_mode = True


class ContactGroupBase(BaseModel):
    group_name: str
    description: Optional[str] = None

class ContactGroupCreate(ContactGroupBase):
    pass

class ContactGroupResponse(ContactGroupBase):
    id: int
    scraped_on: Optional[datetime] = None
    # Could also include a list of members here if desired for some responses
    # members: List[ContactResponse] = []

    class Config:
        orm_mode = True

# For uploading scraped group members
class ScrapedMember(BaseModel):
    phone_number: str
    name_from_profile: Optional[str] = None

class ScrapedGroupUpload(BaseModel):
    group_name: str
    members: List[ScrapedMember]

# --- Datetime import for Pydantic Schemas ---
# Pydantic uses standard datetime, SQLAlchemy uses its own.
from datetime import datetime
# Need to update Optional fields in Pydantic models to use this datetime
ContactResponse.model_fields['created_at'].annotation = Optional[datetime]
ContactResponse.model_fields['updated_at'].annotation = Optional[datetime]
WhatsAppAccountResponse.model_fields['created_at'].annotation = Optional[datetime]
WhatsAppAccountResponse.model_fields['updated_at'].annotation = Optional[datetime]
ConversationBase.model_fields['timestamp'].annotation = Optional[datetime]
ContactGroupResponse.model_fields['scraped_on'].annotation = Optional[datetime]

# --- End of models.py ---
# Remember to call Base.metadata.create_all(bind=engine) in your main application
# startup logic (e.g., in main.py or after database.init_db()) AFTER importing these models.
# For example, in database.py's init_db:
#
# from . import models  # Assuming models.py is in the same directory
# def init_db():
#     Base.metadata.create_all(bind=engine)
#     print("Database tables created (if they didn't exist).")
#
# Or in main.py:
# from .database import engine, Base
# from . import models # Ensure models are loaded
# Base.metadata.create_all(bind=engine)
#
# Choose one place to do this.
# A common practice is to have a startup event in FastAPI or a separate CLI command.
