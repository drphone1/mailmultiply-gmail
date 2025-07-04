from sqlalchemy.orm import Session
from . import models, schemas # models.py and schemas from models.py
from typing import List, Optional

# --- Contact CRUD ---

def get_contact(db: Session, contact_id: int) -> Optional[models.Contact]:
    return db.query(models.Contact).filter(models.Contact.id == contact_id).first()

def get_contact_by_phone(db: Session, phone_number: str) -> Optional[models.Contact]:
    return db.query(models.Contact).filter(models.Contact.phone_number == phone_number).first()

def get_contacts(db: Session, skip: int = 0, limit: int = 100) -> List[models.Contact]:
    return db.query(models.Contact).offset(skip).limit(limit).all()

def create_contact(db: Session, contact: schemas.ContactCreate) -> models.Contact:
    db_contact = models.Contact(**contact.model_dump())
    db.add(db_contact)
    db.commit()
    db.refresh(db_contact)
    return db_contact

def update_contact(db: Session, contact_id: int, contact_update: schemas.ContactCreate) -> Optional[models.Contact]:
    db_contact = get_contact(db, contact_id)
    if db_contact:
        update_data = contact_update.model_dump(exclude_unset=True)
        for key, value in update_data.items():
            setattr(db_contact, key, value)
        db.commit()
        db.refresh(db_contact)
    return db_contact

def delete_contact(db: Session, contact_id: int) -> Optional[models.Contact]:
    db_contact = get_contact(db, contact_id)
    if db_contact:
        db.delete(db_contact)
        db.commit()
    return db_contact

# --- WhatsAppAccount CRUD ---

def get_whatsapp_account(db: Session, account_id: int) -> Optional[models.WhatsAppAccount]:
    return db.query(models.WhatsAppAccount).filter(models.WhatsAppAccount.id == account_id).first()

def get_whatsapp_account_by_phone_id(db: Session, phone_number_id: str) -> Optional[models.WhatsAppAccount]:
    return db.query(models.WhatsAppAccount).filter(models.WhatsAppAccount.phone_number_id == phone_number_id).first()

def get_default_whatsapp_account(db: Session) -> Optional[models.WhatsAppAccount]:
    return db.query(models.WhatsAppAccount).filter(models.WhatsAppAccount.is_default == True).first()

def get_whatsapp_accounts(db: Session, skip: int = 0, limit: int = 10) -> List[models.WhatsAppAccount]:
    return db.query(models.WhatsAppAccount).offset(skip).limit(limit).all()

def create_whatsapp_account(db: Session, account: schemas.WhatsAppAccountCreate) -> models.WhatsAppAccount:
    # If this account is set to default, ensure no other account is default
    if account.is_default:
        current_default = get_default_whatsapp_account(db)
        if current_default:
            current_default.is_default = False
            db.add(current_default)

    db_account = models.WhatsAppAccount(**account.model_dump())
    db.add(db_account)
    db.commit()
    db.refresh(db_account)
    return db_account

def update_whatsapp_account(db: Session, account_id: int, account_update: schemas.WhatsAppAccountCreate) -> Optional[models.WhatsAppAccount]:
    db_account = get_whatsapp_account(db, account_id)
    if db_account:
        update_data = account_update.model_dump(exclude_unset=True)

        # Handle is_default logic: if setting this to default, unset others
        if update_data.get("is_default") == True and not db_account.is_default:
            current_default = get_default_whatsapp_account(db)
            if current_default and current_default.id != db_account.id:
                current_default.is_default = False
                db.add(current_default)

        for key, value in update_data.items():
            setattr(db_account, key, value)
        db.commit()
        db.refresh(db_account)
    return db_account

def delete_whatsapp_account(db: Session, account_id: int) -> Optional[models.WhatsAppAccount]:
    db_account = get_whatsapp_account(db, account_id)
    if db_account:
        # Consider logic for what happens to conversations if an account is deleted
        db.delete(db_account)
        db.commit()
    return db_account


# --- Conversation CRUD ---

def create_conversation_message(db: Session, message: schemas.ConversationCreate) -> models.Conversation:
    # Find or create contact
    contact = get_contact_by_phone(db, message.contact_phone_number)
    if not contact:
        contact_create_schema = schemas.ContactCreate(phone_number=message.contact_phone_number)
        contact = create_contact(db, contact_create_schema)

    # Find WhatsApp account
    # For now, assuming single account or using a passed phone_id to find the account
    # This logic might need to be more robust if multiple accounts can send to the same contact.
    whatsapp_account = get_whatsapp_account_by_phone_id(db, message.whatsapp_account_phone_id)
    if not whatsapp_account:
        # This case should ideally not happen if accounts are pre-configured
        # Or, we might use the 'default' account if no specific one is found/passed
        whatsapp_account = get_default_whatsapp_account(db)
        if not whatsapp_account:
             raise ValueError(f"No WhatsApp account found for phone_id {message.whatsapp_account_phone_id} and no default account set.")


    db_message_data = message.model_dump(exclude={"contact_phone_number", "whatsapp_account_phone_id"})
    db_message = models.Conversation(
        **db_message_data,
        contact_id=contact.id,
        whatsapp_account_id=whatsapp_account.id
    )
    db.add(db_message)
    db.commit()
    db.refresh(db_message)
    return db_message

def get_conversations_for_contact(db: Session, contact_id: int, skip: int = 0, limit: int = 100) -> List[models.Conversation]:
    return db.query(models.Conversation).filter(models.Conversation.contact_id == contact_id).order_by(models.Conversation.timestamp.desc()).offset(skip).limit(limit).all()

# --- ContactGroup and ContactGroupMember CRUD ---

def create_contact_group(db: Session, group: schemas.ContactGroupCreate) -> models.ContactGroup:
    db_group = models.ContactGroup(**group.model_dump())
    db.add(db_group)
    db.commit()
    db.refresh(db_group)
    return db_group

def get_contact_group_by_name(db: Session, group_name: str) -> Optional[models.ContactGroup]:
    return db.query(models.ContactGroup).filter(models.ContactGroup.group_name == group_name).first()

def add_contact_to_group(db: Session, contact_id: int, group_id: int) -> Optional[models.ContactGroupMember]:
    # Check if already a member
    existing_member = db.query(models.ContactGroupMember).filter_by(contact_id=contact_id, group_id=group_id).first()
    if existing_member:
        return existing_member

    db_member = models.ContactGroupMember(contact_id=contact_id, group_id=group_id)
    db.add(db_member)
    db.commit()
    db.refresh(db_member)
    return db_member

def get_contacts_in_group(db: Session, group_id: int) -> List[models.Contact]:
    return db.query(models.Contact).join(models.ContactGroupMember).filter(models.ContactGroupMember.group_id == group_id).all()
