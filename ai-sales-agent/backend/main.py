import os
import io
from typing import List, Optional

from fastapi import FastAPI, File, UploadFile, Form, HTTPException, Request, Response, Depends
from fastapi.responses import JSONResponse, PlainTextResponse
from fastapi.middleware.cors import CORSMiddleware
import httpx # For making async HTTP requests if needed by WhatsApp API sending function
from sqlalchemy.orm import Session
import csv # For parsing CSV files
import vobject # For parsing VCF files (vobject library) - make sure 'vobject' is in requirements.txt

import PyPDF2
import docx # Make sure 'python-docx' is in requirements.txt
import requests
from bs4 import BeautifulSoup # Make sure 'beautifulsoup4' is in requirements.txt
from langchain.text_splitter import RecursiveCharacterTextSplitter # Make sure 'langchain' is in requirements.txt
import chromadb # Make sure 'chromadb' is in requirements.txt
import google.generativeai as genai # Make sure 'google-generativeai' is in requirements.txt

# --- Configuration ---
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
if not GOOGLE_API_KEY:
    print("Warning: GOOGLE_API_KEY not found in environment variables. API calls will fail.")

try:
    genai.configure(api_key=GOOGLE_API_KEY)
    embedding_model = genai.GenerativeModel('models/embedding-001')
except Exception as e:
    print(f"Error configuring Google Generative AI: {e}. Ensure API key is valid and model exists.")
    embedding_model = None

# ChromaDB setup (for RAG knowledge base)
CHROMA_DATA_PATH = "../data_chroma" # Renamed to avoid conflict if user has a general 'data' dir
COLLECTION_NAME = "sales_rag_kb"

# --- Database (PostgreSQL), Models, Schemas, CRUD ---
from . import crud, models, schemas # . refers to current directory
from .database import SessionLocal, engine, get_db, Base as DB_Base

# Create database tables if they don't exist
try:
    DB_Base.metadata.create_all(bind=engine)
    print("PostgreSQL database tables checked/created based on models.py.")
except Exception as e_pg:
    print(f"ERROR connecting to or creating PostgreSQL tables: {e_pg}")
    print("Please ensure your DATABASE_URL in .env is correct and PostgreSQL server is running.")
    # Depending on severity, you might want to exit or prevent app startup
    # For now, it will likely fail later if DB is not available.


# Initialize ChromaDB client (for RAG, separate from PostgreSQL)
try:
    # Ensure ChromaDB data path exists
    os.makedirs(CHROMA_DATA_PATH, exist_ok=True)
    chroma_client = chromadb.PersistentClient(path=CHROMA_DATA_PATH)
    rag_collection = chroma_client.get_or_create_collection(name=COLLECTION_NAME)
    print(f"ChromaDB client and RAG collection '{COLLECTION_NAME}' initialized at '{CHROMA_DATA_PATH}'.")
except Exception as e_chroma:
    print(f"Error initializing ChromaDB: {e_chroma}")
    chroma_client = None
    rag_collection = None


# --- FastAPI App Initialization ---
app = FastAPI(title="AI Sales Agent API")

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Helper Functions for Text Extraction (RAG) ---
def extract_text_from_pdf(file_stream: io.BytesIO) -> str:
    text = ""
    try:
        reader = PyPDF2.PdfReader(file_stream)
        for page in reader.pages:
            text += page.extract_text() or ""
    except Exception as e:
        print(f"Error extracting text from PDF: {e}")
    return text

def extract_text_from_docx(file_stream: io.BytesIO) -> str:
    text = ""
    try:
        doc = docx.Document(file_stream)
        for para in doc.paragraphs:
            text += para.text + "\n"
    except Exception as e:
        print(f"Error extracting text from DOCX: {e}")
    return text

def scrape_text_from_url(url: str) -> str:
    text = ""
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, 'html.parser')
        for script_or_style in soup(["script", "style"]):
            script_or_style.decompose()
        text = soup.get_text(separator='\n', strip=True)
    except requests.exceptions.RequestException as e:
        print(f"Error fetching URL {url}: {e}")
    except Exception as e:
        print(f"Error scraping text from URL {url}: {e}")
    return text

def get_embedding(text_to_embed: str): # Renamed parameter for clarity
    if not embedding_model:
        raise HTTPException(status_code=500, detail="Embedding model not initialized.")
    try:
        result = genai.embed_content(model="models/embedding-001", content=text_to_embed)
        return result['embedding']
    except Exception as e:
        print(f"Error generating embedding: {e}")
        raise HTTPException(status_code=500, detail=f"Error generating embedding: {e}")

# --- Helper Functions for VCF/CSV Parsing (CRM) ---
def parse_vcf_contacts(file_stream: io.BytesIO) -> List[schemas.ContactCreate]:
    # (Implementation from previous step - kept concise for brevity here, assume it's correct)
    # ... (ensure this function correctly parses VCF and returns List[schemas.ContactCreate])
    contacts_data = []
    try:
        vcf_content = file_stream.read().decode('utf-8', errors='ignore')
        for vcard in vobject.readComponents(vcf_content):
            name = None
            phone = None
            email_vcf = None
            if hasattr(vcard, 'fn'): name = str(vcard.fn.value)
            elif hasattr(vcard, 'n'): name = " ".join(filter(None, [vcard.n.value.prefix, vcard.n.value.given, vcard.n.value.additional, vcard.n.value.family, vcard.n.value.suffix]))

            if hasattr(vcard, 'tel_list'):
                # Simple logic: prioritize CELL, then MAIN, then first
                tels = {tel.singletonparams[0] if tel.singletonparams else 'VOICE': str(tel.value) for tel in vcard.tel_list}
                phone = tels.get('CELL') or tels.get('MAIN') or next(iter(tels.values()), None)

            if hasattr(vcard, 'email_list'):
                email_vcf = str(vcard.email_list[0].value)

            if phone:
                # Basic phone normalization (can be greatly improved)
                phone = "".join(filter(str.isdigit, phone))
                if len(phone) > 10 and not phone.startswith('+'): # very naive
                    phone = f"+{phone}"

                contacts_data.append(schemas.ContactCreate(phone_number=phone, name_from_vcf=name, email=email_vcf))
    except Exception as e:
        print(f"Error parsing VCF: {e}")
    return contacts_data


def parse_csv_contacts(file_stream: io.BytesIO) -> List[schemas.ContactCreate]:
    # (Implementation from previous step - kept concise, assume it's correct)
    # ... (ensure this function correctly parses CSV and returns List[schemas.ContactCreate])
    contacts_data = []
    try:
        csv_content = file_stream.read().decode('utf-8', errors='ignore')
        reader = csv.DictReader(io.StringIO(csv_content))
        phone_fields = ['phone', 'phonenumber', 'mobile', 'tel', 'contact', 'number']
        name_fields = ['name', 'fullname', 'contactname']
        email_fields = ['email', 'emailaddress']

        phone_col, name_col, email_col = None, None, None
        if reader.fieldnames:
            lc_fieldnames = [f.lower() for f in reader.fieldnames]
            for i, h in enumerate(lc_fieldnames):
                if not phone_col and h in phone_fields: phone_col = reader.fieldnames[i]
                if not name_col and h in name_fields: name_col = reader.fieldnames[i]
                if not email_col and h in email_fields: email_col = reader.fieldnames[i]

        if not phone_col: raise ValueError("CSV must contain a phone column.")

        for row in reader:
            phone = row.get(phone_col, "").strip()
            phone = "".join(filter(str.isdigit, phone)) # Basic normalization
            if len(phone) > 10 and not phone.startswith('+'): phone = f"+{phone}"

            name = row.get(name_col) if name_col else None
            email_csv = row.get(email_col) if email_col else None
            if phone:
                contacts_data.append(schemas.ContactCreate(phone_number=phone, name_from_vcf=name, email=email_csv))
    except Exception as e:
        print(f"Error parsing CSV contacts: {e}")
    return contacts_data

def parse_csv_scraped_group_members(file_stream: io.BytesIO) -> List[schemas.ScrapedMember]:
    # (Implementation from previous step - kept concise, assume it's correct)
    # ... (ensure this function correctly parses CSV and returns List[schemas.ScrapedMember])
    members_data = []
    try:
        csv_content = file_stream.read().decode('utf-8', errors='ignore')
        reader = csv.DictReader(io.StringIO(csv_content))
        phone_col, name_col = 'phone_number', 'name_from_profile'
        if phone_col not in reader.fieldnames: raise ValueError("CSV must contain 'phone_number' column.")

        for row in reader:
            phone = row.get(phone_col, "").strip()
            phone = "".join(filter(str.isdigit, phone))
            if len(phone) > 10 and not phone.startswith('+'): phone = f"+{phone}"
            name = row.get(name_col)
            if phone:
                members_data.append(schemas.ScrapedMember(phone_number=phone, name_from_profile=name))
    except Exception as e:
        print(f"Error parsing CSV scraped members: {e}")
    return members_data

# --- RAG Knowledge Base API Endpoint ---
@app.post("/ingest", summary="Ingest documents and URLs into RAG knowledge base")
async def ingest_data_endpoint( files: List[UploadFile] = File(None), url: Optional[str] = Form(None)):
    if not files and not url:
        raise HTTPException(status_code=400, detail="No files or URL provided.")
    if not chroma_client or not rag_collection:
        raise HTTPException(status_code=500, detail="ChromaDB RAG collection not initialized.")
    if not embedding_model:
        raise HTTPException(status_code=500, detail="Embedding model not initialized.")

    all_text = ""
    if files:
        for file_obj in files: # Renamed to avoid conflict
            file_stream = io.BytesIO(await file_obj.read())
            filename = file_obj.filename.lower()
            if filename.endswith(".pdf"): all_text += extract_text_from_pdf(file_stream) + "\n"
            elif filename.endswith(".docx"): all_text += extract_text_from_docx(file_stream) + "\n"
            elif filename.endswith(".txt"): all_text += file_stream.read().decode('utf-8', errors='ignore') + "\n"
            else: print(f"Skipping unsupported file: {file_obj.filename}")
            file_stream.close()
    if url: all_text += scrape_text_from_url(url) + "\n"

    if not all_text.strip():
        return JSONResponse(status_code=400, content={"status": "error", "message": "No text content extracted."})

    text_splitter = RecursiveCharacterTextSplitter(chunk_size=800, chunk_overlap=150)
    chunks = text_splitter.split_text(all_text)
    if not chunks:
        return JSONResponse(status_code=400, content={"status": "error", "message": "No text chunks generated."})

    doc_ids, embeddings_list, documents_list = [], [], []
    for i, chunk in enumerate(chunks):
        try:
            embedding = get_embedding(chunk)
            doc_ids.append(f"doc_ingest_{i}_{len(chunk)}") # More unique ID
            embeddings_list.append(embedding)
            documents_list.append(chunk)
        except Exception as e_emb: # Catch embedding errors specifically
            print(f"Error embedding chunk {i}: {e_emb}")
            # Optionally skip or return error
            # For now, we skip the chunk
            continue

    if not documents_list:
         return JSONResponse(status_code=500, content={"status": "error", "message": "No documents could be embedded."})
    try:
        if rag_collection.count() > 0:
            print(f"RAG Collection '{COLLECTION_NAME}' has data. New data will be added.")
        rag_collection.add(embeddings=embeddings_list, documents=documents_list, ids=doc_ids)
    except Exception as e_chroma_add:
        raise HTTPException(status_code=500, detail=f"Error storing data in RAG DB: {e_chroma_add}")

    return JSONResponse(status_code=200, content={"status": "success", "message": f"Knowledge base updated. Added {len(doc_ids)} text chunks."})

# --- Web Chat API Endpoint (RAG based) ---
@app.post("/chat", summary="Handle web chat queries using RAG")
async def chat_with_agent_endpoint(query_request: schemas.ChatQueryRequest, db: Session = Depends(get_db)): # Added db for potential future use
    user_query = query_request.query
    if not user_query:
        raise HTTPException(status_code=400, detail="Query not provided.")
    if not rag_collection or not embedding_model:
        raise HTTPException(status_code=500, detail="RAG or Embedding model not initialized.")

    try:
        query_embedding = get_embedding(user_query)
        results = rag_collection.query(query_embeddings=[query_embedding], n_results=4, include=['documents'])
        retrieved_chunks = results.get('documents', [[]])[0]
        context_for_llm = "\n---\n".join(retrieved_chunks) if retrieved_chunks else "No specific information found."

        default_wa_account = crud.get_default_whatsapp_account(db) # Get company name from default account if set
        my_company_name = default_wa_account.account_name if default_wa_account else "[My Company Name]"

        final_prompt = f"""You are an expert, friendly, and highly effective AI sales agent for '{my_company_name}'. Your goal is to help customers and persuade them to buy our products. Use the following context, which contains information from our company's documents and website, to answer the user's question. Answer only based on the provided context. If the answer is not in the context, politely state that you do not have that specific information.
CONTEXT:
---
{context_for_llm}
---
USER'S QUESTION:
{user_query}"""
        if not GOOGLE_API_KEY or not genai:
            answer = "AI model (LLM) is not configured."
        else:
            chat_model = genai.GenerativeModel('gemini-pro')
            llm_response = chat_model.generate_content(final_prompt)
            answer = llm_response.text if hasattr(llm_response, 'text') else str(llm_response)
        return schemas.ChatResponse(response=answer)
    except Exception as e_chat:
        print(f"Error in /chat endpoint: {e_chat}")
        raise HTTPException(status_code=500, detail=f"An unexpected error occurred: {e_chat}")


# --- WhatsApp Integration ---
WHATSAPP_VERIFY_TOKEN = os.getenv("WHATSAPP_VERIFY_TOKEN", "YOUR_ENV_VERIFY_TOKEN") # Ensure this is set in .env

async def send_whatsapp_message_via_api(db: Session, to_phone_number: str, message_body: str, whatsapp_account_id: int):
    whatsapp_account = crud.get_whatsapp_account(db, account_id=whatsapp_account_id)
    if not whatsapp_account or not whatsapp_account.access_token or not whatsapp_account.phone_number_id:
        print(f"Error: WhatsApp account ID {whatsapp_account_id} not configured correctly.")
        # Log this failure to DB
        crud.create_conversation_message(db=db, message=schemas.ConversationCreate(
            contact_phone_number=to_phone_number,
            whatsapp_account_phone_id="UNKNOWN_ACCOUNT_CONFIG_ERROR", # Placeholder
            sender_phone="SYSTEM",
            receiver_phone=to_phone_number,
            message_text=message_body,
            direction=schemas.MessageDirection.OUTBOUND,
            status="failed_account_config"
        ))
        return {"status": "error", "message": "WhatsApp account not configured."}

    print(f"Attempting to send WhatsApp message to {to_phone_number} using account {whatsapp_account.account_name}: {message_body}")
    api_url = f"https://graph.facebook.com/v18.0/{whatsapp_account.phone_number_id}/messages" # Example, adjust version as needed
    headers = {"Authorization": f"Bearer {whatsapp_account.access_token}", "Content-Type": "application/json"}
    payload = {"messaging_product": "whatsapp", "to": to_phone_number, "type": "text", "text": {"body": message_body}}

    response_status, wa_message_id = "failed_api_error", None
    try:
        async with httpx.AsyncClient() as client:
            api_response = await client.post(api_url, json=payload, headers=headers)
            api_response.raise_for_status()
            wa_message_id = api_response.json().get("messages",[{}])[0].get("id")
            response_status = "sent_to_api" # Or parse actual status from API response
            print(f"WhatsApp message API call successful (WA_Msg_ID: {wa_message_id}): {api_response.json()}")
    except httpx.HTTPStatusError as e_http:
        print(f"Error sending WhatsApp message (HTTP): {e_http.response.status_code} - {e_http.response.text}")
        response_status = f"failed_http_{e_http.response.status_code}"
    except Exception as e_gen:
        print(f"Generic error sending WhatsApp message: {e_gen}")
        response_status = "failed_exception"

    # Log outbound message to DB
    crud.create_conversation_message(db=db, message=schemas.ConversationCreate(
        contact_phone_number=to_phone_number,
        whatsapp_account_phone_id=whatsapp_account.phone_number_id,
        sender_phone=whatsapp_account.phone_number_id,
        receiver_phone=to_phone_number,
        message_text=message_body,
        direction=schemas.MessageDirection.OUTBOUND,
        status=response_status,
        message_id_whatsapp=wa_message_id
    ))
    return {"status": "success" if response_status == "sent_to_api" else "error", "wa_message_id": wa_message_id}

@app.get("/whatsapp/webhook", summary="Verify WhatsApp webhook")
async def whatsapp_webhook_verify_endpoint(request: Request):
    print("GET /whatsapp/webhook received for verification")
    mode = request.query_params.get("hub.mode")
    token = request.query_params.get("hub.verify_token")
    challenge = request.query_params.get("hub.challenge")
    if not WHATSAPP_VERIFY_TOKEN or WHATSAPP_VERIFY_TOKEN == "YOUR_ENV_VERIFY_TOKEN":
        print("ERROR: WHATSAPP_VERIFY_TOKEN is not set correctly in .env.")
        raise HTTPException(status_code=500, detail="Server verify token not configured.")
    if mode == "subscribe" and token == WHATSAPP_VERIFY_TOKEN:
        print(f"Webhook verified! Responding with challenge: {challenge}")
        return PlainTextResponse(content=challenge, status_code=200)
    else:
        print("Webhook verification failed: Mode or token mismatch.")
        raise HTTPException(status_code=403, detail="Forbidden: Verification token mismatch")

@app.post("/whatsapp/webhook", summary="Handle incoming WhatsApp messages")
async def whatsapp_webhook_handler_endpoint(request: Request, db: Session = Depends(get_db)):
    print("POST /whatsapp/webhook received event")
    payload = await request.json()
    print(f"Received payload: {payload}")

    default_wa_account = crud.get_default_whatsapp_account(db)
    if not default_wa_account:
        print("ERROR: No default WhatsApp account configured to receive messages.")
        return Response(content="EVENT_RECEIVED_NO_DEFAULT_ACCOUNT_CONFIGURED", status_code=200)

    try:
        if payload.get("object") == "whatsapp_business_account":
            for entry in payload.get("entry", []):
                for change in entry.get("changes", []):
                    value = change.get("value", {})
                    if value.get("metadata", {}).get("phone_number_id") != default_wa_account.phone_number_id:
                        print(f"Webhook for other account ({value.get('metadata', {}).get('phone_number_id')}), skipping.")
                        continue # Process only for the default account's phone_number_id

                    # Handle incoming messages
                    if "messages" in value:
                        for message_data in value.get("messages", []):
                            user_phone_number = message_data.get("from")
                            message_id_whatsapp = message_data.get("id")
                            message_type = message_data.get("type")

                            if not user_phone_number:
                                print("Skipping message: no sender phone number.")
                                continue

                            message_text_content = None
                            if message_type == "text":
                                message_text_content = message_data.get("text", {}).get("body")
                            else: # For non-text, store a placeholder
                                message_text_content = f"[{message_type.upper()} MESSAGE RECEIVED]"

                            print(f"Incoming '{message_type}' from {user_phone_number} (WA_ID: {message_id_whatsapp}): {message_text_content if message_type == 'text' else ''}")

                            # Save incoming message
                            crud.create_conversation_message(db=db, message=schemas.ConversationCreate(
                                contact_phone_number=user_phone_number,
                                whatsapp_account_phone_id=default_wa_account.phone_number_id,
                                sender_phone=user_phone_number,
                                receiver_phone=default_wa_account.phone_number_id,
                                message_text=message_text_content,
                                direction=schemas.MessageDirection.INBOUND,
                                status="received",
                                message_id_whatsapp=message_id_whatsapp
                            ))

                            if message_type == "text" and message_text_content:
                                # --- RAG + LLM response generation ---
                                try:
                                    if not rag_collection or not embedding_model:
                                        ai_response_text = "AI knowledge base is not available."
                                    elif not GOOGLE_API_KEY or not genai:
                                        ai_response_text = "AI model (LLM) is not configured."
                                    else:
                                        query_embedding = get_embedding(message_text_content)
                                        results = rag_collection.query(query_embeddings=[query_embedding], n_results=3, include=['documents'])
                                        retrieved_chunks = results.get('documents', [[]])[0]
                                        context_for_llm = "\n---\n".join(retrieved_chunks) if retrieved_chunks else "No specific information found."

                                        company_name_for_prompt = default_wa_account.account_name or "[My Company Name]"
                                        final_prompt = f"""You are an expert, friendly AI sales agent for '{company_name_for_prompt}'. Use the CONTEXT to answer the USER'S QUESTION. If the answer isn't in CONTEXT, say you don't have that info.
CONTEXT:
---
{context_for_llm}
---
USER'S QUESTION (from WhatsApp user {user_phone_number}):
{message_text_content}"""
                                        chat_model_llm = genai.GenerativeModel('gemini-pro') # make configurable later
                                        llm_response = chat_model_llm.generate_content(final_prompt)
                                        ai_response_text = llm_response.text if hasattr(llm_response, 'text') else str(llm_response)

                                    print(f"AI Response for {user_phone_number}: {ai_response_text}")
                                    await send_whatsapp_message_via_api(db, user_phone_number, ai_response_text, default_wa_account.id)
                                except Exception as e_rag_llm:
                                    print(f"Error during RAG/LLM for {user_phone_number}: {e_rag_llm}")
                                    error_reply = "Sorry, I had trouble processing that with AI."
                                    await send_whatsapp_message_via_api(db, user_phone_number, error_reply, default_wa_account.id)

                    # Handle message status updates
                    elif "statuses" in value:
                        for status_data in value.get("statuses", []):
                            wa_msg_id_status = status_data.get("id")
                            status_val = status_data.get("status")
                            # TODO: Implement crud.update_conversation_status_by_whatsapp_id(db, wa_msg_id_status, status_val)
                            print(f"Status update for WA_Msg_ID {wa_msg_id_status}: {status_val}")
        return Response(content="EVENT_RECEIVED_PROCESSED", status_code=200)
    except Exception as e_webhook:
        print(f"FATAL Error in WhatsApp webhook: {e_webhook}")
        return Response(content="Error processing webhook event", status_code=200) # Always 200 to WA

# --- CRM API Endpoints ---
@app.post("/whatsapp_accounts/", response_model=schemas.WhatsAppAccountResponse, status_code=201, summary="Create a WhatsApp Business Account configuration")
def admin_create_wa_account(account: schemas.WhatsAppAccountCreate, db: Session = Depends(get_db)):
    db_account = crud.get_whatsapp_account_by_phone_id(db, phone_number_id=account.phone_number_id)
    if db_account:
        raise HTTPException(status_code=400, detail="Account with this phone_number_id already exists.")
    return crud.create_whatsapp_account(db=db, account=account)

@app.get("/whatsapp_accounts/", response_model=List[schemas.WhatsAppAccountResponse], summary="List configured WhatsApp accounts")
def admin_read_wa_accounts(skip: int = 0, limit: int = 10, db: Session = Depends(get_db)):
    return crud.get_whatsapp_accounts(db, skip=skip, limit=limit)

@app.get("/whatsapp_accounts/default", response_model=Optional[schemas.WhatsAppAccountResponse], summary="Get the default WhatsApp account")
def admin_get_default_wa_account(db: Session = Depends(get_db)):
    # Returns null (None) if no default is set, which is fine for frontend to check.
    return crud.get_default_whatsapp_account(db)

@app.put("/whatsapp_accounts/{account_id}", response_model=schemas.WhatsAppAccountResponse, summary="Update a WhatsApp account")
def admin_update_wa_account(account_id: int, account_update_data: schemas.WhatsAppAccountCreate, db: Session = Depends(get_db)):
    updated_account = crud.update_whatsapp_account(db, account_id=account_id, account_update=account_update_data)
    if not updated_account:
        raise HTTPException(status_code=404, detail="WhatsApp account not found.")
    return updated_account

@app.post("/contacts/upload_vcf_csv", status_code=201, summary="Upload contacts from VCF or CSV file")
async def admin_upload_contacts_file(file: UploadFile = File(...), db: Session = Depends(get_db)):
    if not (file.filename.lower().endswith(".vcf") or file.filename.lower().endswith(".csv")):
        raise HTTPException(status_code=400, detail="Invalid file type. Upload VCF or CSV.")

    file_stream = io.BytesIO(await file.read())
    created_count, updated_count, failed_count = 0, 0, 0
    errors_log = []
    parsed_contacts_list: List[schemas.ContactCreate] = [] # Explicit type
    try:
        if file.filename.lower().endswith(".vcf"): parsed_contacts_list = parse_vcf_contacts(file_stream)
        elif file.filename.lower().endswith(".csv"): parsed_contacts_list = parse_csv_contacts(file_stream)
    except Exception as e_parse:
        raise HTTPException(status_code=400, detail=f"Error parsing file: {str(e_parse)}")

    for p_contact in parsed_contacts_list:
        try:
            db_contact = crud.get_contact_by_phone(db, phone_number=p_contact.phone_number)
            if db_contact:
                crud.update_contact(db, contact_id=db_contact.id, contact_update=p_contact)
                updated_count +=1
            else:
                crud.create_contact(db, contact=p_contact)
                created_count +=1
        except Exception as e_db_contact:
            failed_count +=1
            errors_log.append({"phone": p_contact.phone_number, "error": str(e_db_contact)})
    return {"message": f"Contacts: {created_count} new, {updated_count} updated, {failed_count} failed.", "errors": errors_log}

@app.post("/contacts/upload_scraped_group_data", status_code=201, summary="Upload scraped group members from CSV")
async def admin_upload_scraped_data(group_name: str = Form(...), file: UploadFile = File(...), db: Session = Depends(get_db)):
    if not file.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="Upload CSV for scraped data.")

    file_stream = io.BytesIO(await file.read())
    parsed_members_list: List[schemas.ScrapedMember] = [] # Explicit type
    try:
        parsed_members_list = parse_csv_scraped_group_members(file_stream)
    except Exception as e_parse_scraped:
        raise HTTPException(status_code=400, detail=f"Error parsing scraped CSV: {str(e_parse_scraped)}")

    contact_group = crud.get_contact_group_by_name(db, group_name=group_name)
    if not contact_group:
        contact_group = crud.create_contact_group(db, group=schemas.ContactGroupCreate(group_name=group_name))

    linked_count, new_contacts_count, errors_log = 0, 0, []
    for member_data in parsed_members_list:
        try:
            contact = crud.get_contact_by_phone(db, phone_number=member_data.phone_number)
            if not contact:
                contact_create_data = schemas.ContactCreate(phone_number=member_data.phone_number, name_from_vcf=member_data.name_from_profile)
                contact = crud.create_contact(db, contact=contact_create_data)
                new_contacts_count += 1
            if crud.add_contact_to_group(db, contact_id=contact.id, group_id=contact_group.id):
                linked_count +=1
        except Exception as e_db_group:
            errors_log.append({"phone": member_data.phone_number, "error": str(e_db_group)})
    return {"message": f"Group '{group_name}': {new_contacts_count} new contacts, {linked_count} members linked. Errors: {len(errors_log)}.", "errors": errors_log}

@app.get("/contacts/", response_model=List[schemas.ContactResponse], summary="List all contacts")
def admin_read_contacts(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    return crud.get_contacts(db, skip=skip, limit=limit)

@app.get("/contacts/{contact_id}", response_model=schemas.ContactResponse, summary="Get a specific contact by ID")
def admin_read_contact(contact_id: int, db: Session = Depends(get_db)):
    db_contact = crud.get_contact(db, contact_id=contact_id)
    if not db_contact: raise HTTPException(status_code=404, detail="Contact not found")
    return db_contact

@app.get("/contacts/{contact_id}/conversations", response_model=List[schemas.ConversationResponse], summary="Get conversations for a contact")
def admin_read_contact_conversations(contact_id: int, skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    if not crud.get_contact(db, contact_id=contact_id):
        raise HTTPException(status_code=404, detail="Contact not found.")
    return crud.get_conversations_for_contact(db, contact_id=contact_id, skip=skip, limit=limit)

# --- Main execution (for local development) ---
if __name__ == "__main__":
    import uvicorn
    from dotenv import load_dotenv # Ensure dotenv is imported for __main__
    load_dotenv()

    print(f"Attempting to connect to database: {os.getenv('DATABASE_URL')}")
    # Table creation is now at the top of the file.

    if not GOOGLE_API_KEY: print("ERROR: GOOGLE_API_KEY environment variable is not set.")
    else: print("GOOGLE_API_KEY found.")

    if not WHATSAPP_VERIFY_TOKEN or WHATSAPP_VERIFY_TOKEN == "YOUR_ENV_VERIFY_TOKEN":
        print("WARNING: WHATSAPP_VERIFY_TOKEN is not set correctly in .env. Webhook verification might fail.")

    # ChromaDB data path already created at top if needed.
    print(f"ChromaDB data path: {os.path.abspath(CHROMA_DATA_PATH)}")

    print("Starting FastAPI server on http://0.0.0.0:8000")
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)

# General Instructions:
# 1. Create .env in backend/: `DATABASE_URL=postgresql://user:pass@host:port/db`, `GOOGLE_API_KEY=...`, `WHATSAPP_VERIFY_TOKEN=...`
# 2. `pip install -r requirements.txt` (ensure `vobject`, `python-docx`, `langchain`, etc. are listed)
# 3. Run: `python main.py`
# 4. For WhatsApp Webhook: Use ngrok (`./ngrok http 8000`), provide HTTPS URL to Meta. Configure a default WA account via API/Admin.
