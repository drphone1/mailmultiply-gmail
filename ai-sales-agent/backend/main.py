import os
import io
from typing import List, Optional

from fastapi import FastAPI, File, UploadFile, Form, HTTPException, Request, Response
from fastapi.responses import JSONResponse, PlainTextResponse
from fastapi.middleware.cors import CORSMiddleware # Import for CORS
import httpx # For making async HTTP requests if needed by WhatsApp API sending function

import PyPDF2
import docx
import requests
from bs4 import BeautifulSoup
from langchain.text_splitter import RecursiveCharacterTextSplitter
import chromadb
import google.generativeai as genai

# --- Configuration ---
# IMPORTANT: Set your GOOGLE_API_KEY environment variable before running the app.
# You can do this by running `export GOOGLE_API_KEY='your_api_key_here'` in your terminal
# or by setting it directly in your environment.
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
if not GOOGLE_API_KEY:
    print("Warning: GOOGLE_API_KEY not found in environment variables. API calls will fail.")
    # raise ValueError("GOOGLE_API_KEY not found in environment variables.") # Or handle more gracefully

# Configure the generative AI model
try:
    genai.configure(api_key=GOOGLE_API_KEY)
    embedding_model = genai.GenerativeModel('models/embedding-001')
    # It's good practice to specify the model name for chat completions too
    # For example: genai.GenerativeModel('gemini-pro')
    # However, the prompt uses a generic 'generative model', so we'll prepare for that.
except Exception as e:
    print(f"Error configuring Google Generative AI: {e}. Ensure API key is valid and model exists.")
    embedding_model = None # Set to None to indicate failure

# ChromaDB setup
CHROMA_DATA_PATH = "../data" # Relative to main.py
COLLECTION_NAME = "sales_data"

# Initialize ChromaDB client
try:
    client = chromadb.PersistentClient(path=CHROMA_DATA_PATH)
    # Get or create the collection
    collection = client.get_or_create_collection(name=COLLECTION_NAME)
except Exception as e:
    print(f"Error initializing ChromaDB: {e}")
    client = None
    collection = None


# --- FastAPI App Initialization ---
app = FastAPI()

# Add CORS middleware to allow requests from the frontend
# This is important for local development when frontend and backend are on different ports.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allows all origins
    allow_credentials=True,
    allow_methods=["*"],  # Allows all methods
    allow_headers=["*"],  # Allows all headers
)


# --- Helper Functions ---
def extract_text_from_pdf(file_stream: io.BytesIO) -> str:
    """Extracts text from a PDF file stream."""
    try:
        reader = PyPDF2.PdfReader(file_stream)
        text = ""
        for page in reader.pages:
            text += page.extract_text() or ""
        return text
    except Exception as e:
        print(f"Error extracting text from PDF: {e}")
        return ""

def extract_text_from_docx(file_stream: io.BytesIO) -> str:
    """Extracts text from a DOCX file stream."""
    try:
        doc = docx.Document(file_stream)
        text = ""
        for para in doc.paragraphs:
            text += para.text + "\n"
        return text
    except Exception as e:
        print(f"Error extracting text from DOCX: {e}")
        return ""

def scrape_text_from_url(url: str) -> str:
    """Scrapes all text content from a given URL."""
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()  # Raise an exception for HTTP errors
        soup = BeautifulSoup(response.content, 'html.parser')
        # Remove script and style elements
        for script_or_style in soup(["script", "style"]):
            script_or_style.decompose()
        text = soup.get_text(separator='\n', strip=True)
        return text
    except requests.exceptions.RequestException as e:
        print(f"Error fetching URL {url}: {e}")
        return ""
    except Exception as e:
        print(f"Error scraping text from URL {url}: {e}")
        return ""

def get_embedding(text: str):
    """Generates embedding for a given text using Google's model."""
    if not embedding_model:
        raise HTTPException(status_code=500, detail="Embedding model not initialized.")
    try:
        result = genai.embed_content(model="models/embedding-001", content=text)
        return result['embedding']
    except Exception as e:
        print(f"Error generating embedding: {e}")
        # Potentially raise HTTPException or return a specific error indicator
        raise HTTPException(status_code=500, detail=f"Error generating embedding: {e}")


# --- API Endpoints ---
@app.post("/ingest")
async def ingest_data(
    files: List[UploadFile] = File(None),
    url: Optional[str] = Form(None)
):
    """
    Endpoint to ingest data from uploaded files (PDF, DOCX, TXT) and/or a website URL.
    Processes the text and stores it in ChromaDB.
    """
    if not files and not url:
        raise HTTPException(status_code=400, detail="No files or URL provided.")
    if not client or not collection:
        raise HTTPException(status_code=500, detail="ChromaDB not initialized.")
    if not embedding_model:
        raise HTTPException(status_code=500, detail="Embedding model not initialized. Check GOOGLE_API_KEY.")

    all_text = ""

    # Process uploaded files
    if files:
        for file in files:
            file_stream = io.BytesIO(await file.read())
            filename = file.filename.lower()
            if filename.endswith(".pdf"):
                print(f"Processing PDF: {file.filename}")
                all_text += extract_text_from_pdf(file_stream) + "\n"
            elif filename.endswith(".docx"):
                print(f"Processing DOCX: {file.filename}")
                all_text += extract_text_from_docx(file_stream) + "\n"
            elif filename.endswith(".txt"):
                print(f"Processing TXT: {file.filename}")
                all_text += file_stream.read().decode('utf-8', errors='ignore') + "\n"
            else:
                print(f"Skipping unsupported file: {file.filename}")
            file_stream.close()

    # Process URL
    if url:
        print(f"Processing URL: {url}")
        all_text += scrape_text_from_url(url) + "\n"

    if not all_text.strip():
        return JSONResponse(
            status_code=400,
            content={"status": "error", "message": "No text content extracted from provided sources."}
        )

    # Split text into chunks
    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=800,
        chunk_overlap=150,
        length_function=len
    )
    chunks = text_splitter.split_text(all_text)
    print(f"Split text into {len(chunks)} chunks.")

    if not chunks:
        return JSONResponse(
            status_code=400,
            content={"status": "error", "message": "No text chunks generated after processing."}
        )

    # Generate embeddings and store in ChromaDB
    doc_ids = []
    embeddings_list = []
    documents_list = []

    for i, chunk in enumerate(chunks):
        try:
            embedding = get_embedding(chunk)
            doc_ids.append(f"doc_{i}") # Simple unique ID for each chunk
            embeddings_list.append(embedding)
            documents_list.append(chunk)
        except HTTPException as e: # Catch embedding errors specifically
            return JSONResponse(
                status_code=e.status_code,
                content={"status": "error", "message": f"Failed to process chunk {i+1}/{len(chunks)}: {e.detail}"}
            )
        except Exception as e:
            print(f"Skipping chunk {i} due to error during embedding: {e}")
            continue # Skip this chunk and try to process others

    if not documents_list:
         return JSONResponse(
            status_code=500,
            content={"status": "error", "message": "No documents could be embedded. Check embedding model and API key."}
        )

    try:
        # Clear existing data in the collection before adding new data for simplicity.
        # For production, you might want a more sophisticated update strategy.
        # Count items before clearing (optional, for logging)
        # current_count = collection.count()
        # if current_count > 0:
        #     print(f"Clearing {current_count} existing items from collection '{COLLECTION_NAME}'...")
        #     # This is a bit tricky with ChromaDB's API for "all" items.
        #     # A common way is to delete by IDs if you know them, or recreate the collection.
        #     # For simplicity here, we'll just add, which might lead to duplicates if run multiple times
        #     # without a proper clearing mechanism. A better way is to manage IDs.
        #     # Or, delete and recreate the collection:
        #     # client.delete_collection(name=COLLECTION_NAME)
        #     # collection = client.get_or_create_collection(name=COLLECTION_NAME)
        #     # print(f"Collection '{COLLECTION_NAME}' cleared and recreated.")
        #
        # Let's assume for now we are adding, and duplicates are handled by the user or by ID management
        # If the collection might contain old data, it's better to clear it first.
        # One way to clear (if you don't care about existing data):
        if collection.count() > 0:
            print(f"Collection '{COLLECTION_NAME}' already has data. For this example, we will add to it. Consider a clearing strategy for production.")
            # client.delete_collection(name=COLLECTION_NAME)
            # collection = client.get_or_create_collection(name=COLLECTION_NAME)
            # print(f"Collection '{COLLECTION_NAME}' cleared and recreated for new ingestion.")


        collection.add(
            embeddings=embeddings_list,
            documents=documents_list,
            ids=doc_ids
        )
        print(f"Successfully added {len(doc_ids)} items to ChromaDB collection '{COLLECTION_NAME}'.")
    except Exception as e:
        print(f"Error adding data to ChromaDB: {e}")
        raise HTTPException(status_code=500, detail=f"Error storing data in vector database: {e}")

    return JSONResponse(
        status_code=200,
        content={"status": "success", "message": f"Knowledge base updated. Added {len(doc_ids)} text chunks."}
    )


@app.post("/chat")
async def chat_with_agent(query_request: dict):
    """
    Endpoint to handle chat queries.
    Retrieves relevant context from ChromaDB and uses a generative model to answer.
    """
    user_query = query_request.get("query")
    if not user_query:
        raise HTTPException(status_code=400, detail="Query not provided.")
    if not client or not collection:
        raise HTTPException(status_code=500, detail="ChromaDB not initialized.")
    if not embedding_model: # Check if embedding model is available
        raise HTTPException(status_code=500, detail="Embedding model not initialized. Cannot process query.")

    try:
        # 1. Generate embedding for the user's query
        query_embedding = get_embedding(user_query)

        # 2. Query ChromaDB for top 4 similar text chunks
        results = collection.query(
            query_embeddings=[query_embedding],
            n_results=4,
            include=['documents'] # We only need the document text
        )

        retrieved_chunks = results.get('documents', [[]])[0] # Get documents from the first query result

        if not retrieved_chunks:
            # Fallback if no relevant documents are found
            context_for_llm = "No specific information found in the knowledge base for this query."
        else:
            context_for_llm = "\n---\n".join(retrieved_chunks)

        # 3. Construct the prompt for the generative model
        # IMPORTANT: Replace '[My Company Name]' with your actual company name.
        my_company_name = "[My Company Name]" # Placeholder
        final_prompt = f"""You are an expert, friendly, and highly effective AI sales agent for '{my_company_name}'. Your goal is to help customers and persuade them to buy our products. Use the following context, which contains information from our company's documents and website, to answer the user's question. Answer only based on the provided context. If the answer is not in the context, politely state that you do not have that specific information.

CONTEXT:
---
{context_for_llm}
---

USER'S QUESTION:
{user_query}"""

        # 4. Send the prompt to the generative model (e.g., Gemini Pro)
        # This is a placeholder for the actual API call.
        # You'll need to use the `google.generativeai` library correctly here.
        # For example, using `genai.GenerativeModel('gemini-pro').generate_content(...)`
        print(f"\n--- Sending to LLM --- \nPrompt: {final_prompt}\n---------------------\n")

        # Placeholder for LLM interaction
        # Replace with actual call to genai.GenerativeModel('gemini-pro').generate_content()
        try:
            # Example: Using Gemini Pro (ensure this model is available and configured)
            chat_model = genai.GenerativeModel('gemini-pro') # Or your chosen chat model
            llm_response = chat_model.generate_content(final_prompt)
            # Accessing the text part of the response, structure might vary by model/API version
            answer = llm_response.text if hasattr(llm_response, 'text') else str(llm_response)

        except Exception as e:
            print(f"Error during LLM call: {e}")
            # Provide a fallback response if the LLM call fails
            answer = "I am currently experiencing technical difficulties and cannot process your request. Please try again later."
            # Optionally, re-raise or return a specific error response
            # raise HTTPException(status_code=503, detail=f"LLM service unavailable: {e}")


        return JSONResponse(content={"response": answer})

    except HTTPException as e: # Re-raise HTTPExceptions to return proper FastAPI responses
        raise e
    except Exception as e:
        print(f"Error in /chat endpoint: {e}")
        raise HTTPException(status_code=500, detail=f"An unexpected error occurred: {e}")


# --- WhatsApp Integration (Placeholder) ---

# IMPORTANT: You will need to replace these placeholders with actual logic
# using your chosen WhatsApp API provider (e.g., Twilio, Meta directly).

# This is a placeholder for your WhatsApp Business API token or provider's API key
WHATSAPP_ACCESS_TOKEN = os.getenv("WHATSAPP_ACCESS_TOKEN", "YOUR_WHATSAPP_ACCESS_TOKEN")
# This is a placeholder for your WhatsApp Business Account phone number ID
WHATSAPP_PHONE_NUMBER_ID = os.getenv("WHATSAPP_PHONE_NUMBER_ID", "YOUR_WHATSAPP_PHONE_NUMBER_ID")
# This is the verification token you set in the Meta/Twilio dashboard for webhook setup
WHATSAPP_VERIFY_TOKEN = os.getenv("WHATSAPP_VERIFY_TOKEN", "YOUR_CHOSEN_VERIFY_TOKEN")

async def send_whatsapp_message(to_phone_number: str, message_body: str):
    """
    Placeholder function to send a message via WhatsApp API.
    You need to implement this using your WhatsApp API provider's SDK or HTTP requests.
    Example for Meta Graph API (conceptual):
    """
    print(f"Attempting to send WhatsApp message to {to_phone_number}: {message_body}")
    if WHATSAPP_ACCESS_TOKEN == "YOUR_WHATSAPP_ACCESS_TOKEN" or WHATSAPP_PHONE_NUMBER_ID == "YOUR_WHATSAPP_PHONE_NUMBER_ID":
        print("WARNING: WhatsApp API credentials are not set. Skipping actual message send.")
        return {"status": "warning", "message": "WhatsApp API credentials not set."}

    # Example using Meta's Graph API structure (requires httpx or requests library)
    # Adjust URL and payload according to your provider's documentation
    api_url = f"https://graph.facebook.com/v18.0/{WHATSAPP_PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {WHATSAPP_ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": to_phone_number,
        "type": "text",
        "text": {"body": message_body},
    }

    try:
        async with httpx.AsyncClient() as client_http:
            response = await client_http.post(api_url, json=payload, headers=headers)
            response.raise_for_status()  # Raise an exception for HTTP errors
            print(f"WhatsApp message sent successfully: {response.json()}")
            return {"status": "success", "response": response.json()}
    except httpx.HTTPStatusError as e:
        print(f"Error sending WhatsApp message: {e.response.status_code} - {e.response.text}")
        return {"status": "error", "message": f"HTTP Error: {e.response.status_code} - {e.response.text}"}
    except Exception as e:
        print(f"Generic error sending WhatsApp message: {e}")
        return {"status": "error", "message": str(e)}


@app.get("/whatsapp/webhook")
async def whatsapp_webhook_verify(request: Request):
    """
    Webhook verification for WhatsApp.
    (Usually required by Meta/Twilio during webhook setup)
    """
    print("GET /whatsapp/webhook received for verification")
    # Extract query parameters for verification
    mode = request.query_params.get("hub.mode")
    token = request.query_params.get("hub.verify_token")
    challenge = request.query_params.get("hub.challenge")

    print(f"Mode: {mode}, Token: {token}, Challenge: {challenge}")

    if mode and token:
        if mode == "subscribe" and token == WHATSAPP_VERIFY_TOKEN:
            print(f"Webhook verified successfully! Responding with challenge: {challenge}")
            return PlainTextResponse(content=challenge, status_code=200)
        else:
            print("Webhook verification failed: Mode or token mismatch.")
            raise HTTPException(status_code=403, detail="Verification token mismatch")
    else:
        print("Webhook verification failed: Missing mode or token.")
        raise HTTPException(status_code=400, detail="Missing verification parameters")


@app.post("/whatsapp/webhook")
async def whatsapp_webhook_handler(request: Request):
    """
    Handles incoming WhatsApp messages.
    """
    print("POST /whatsapp/webhook received message")
    try:
        payload = await request.json()
        print(f"Received payload: {payload}")

        # --- Payload structure can vary greatly based on provider and message type ---
        # This is a common structure for Meta's API for text messages.
        # You MUST adapt this to your specific provider's payload structure.
        # Example: Twilio payload is different.

        # Check if it's a message notification
        if payload.get("object") == "whatsapp_business_account":
            entries = payload.get("entry", [])
            for entry in entries:
                changes = entry.get("changes", [])
                for change in changes:
                    value = change.get("value", {})
                    if value.get("messaging_product") == "whatsapp":
                        messages = value.get("messages", [])
                        if messages: # If there are messages
                            message_data = messages[0] # Process the first message
                            if message_data.get("type") == "text":
                                user_phone_number = message_data.get("from")
                                user_query = message_data.get("text", {}).get("body")
                                message_id = message_data.get("id") # Useful for logging/deduplication

                                print(f"Received message from {user_phone_number}: '{user_query}' (ID: {message_id})")

                                if not user_query or not user_phone_number:
                                    print("Missing user query or phone number in message.")
                                    continue # Skip this message

                                # --- Use RAG pipeline to get an answer ---
                                try:
                                    query_embedding = get_embedding(user_query)
                                    results = collection.query(
                                        query_embeddings=[query_embedding],
                                        n_results=4, # Top 4 chunks
                                        include=['documents']
                                    )
                                    retrieved_chunks_list = results.get('documents', [[]])
                                    retrieved_chunks = retrieved_chunks_list[0] if retrieved_chunks_list else []

                                    if not retrieved_chunks:
                                        context_for_llm = "No specific information found in the knowledge base for this query."
                                    else:
                                        context_for_llm = "\n---\n".join(retrieved_chunks)

                                    my_company_name = "[My Company Name]" # Placeholder
                                    final_prompt = f"""You are an expert, friendly, and highly effective AI sales agent for '{my_company_name}'. Your goal is to help customers and persuade them to buy our products. Use the following context, which contains information from our company's documents and website, to answer the user's question. Answer only based on the provided context. If the answer is not in the context, politely state that you do not have that specific information.

CONTEXT:
---
{context_for_llm}
---

USER'S QUESTION (from WhatsApp):
{user_query}"""

                                    print(f"\n--- Sending to LLM (from WhatsApp) --- \nPrompt: {final_prompt}\n---------------------\n")

                                    # Ensure genai and chat_model are initialized
                                    if not GOOGLE_API_KEY or not genai:
                                        ai_response = "AI model is not configured. Please contact support."
                                    else:
                                        chat_model = genai.GenerativeModel('gemini-pro')
                                        llm_response_obj = chat_model.generate_content(final_prompt)
                                        ai_response = llm_response_obj.text if hasattr(llm_response_obj, 'text') else str(llm_response_obj)

                                    print(f"AI Response: {ai_response}")

                                    # Send the AI's response back to the user via WhatsApp
                                    await send_whatsapp_message(user_phone_number, ai_response)

                                except Exception as e:
                                    print(f"Error processing message for {user_phone_number}: {e}")
                                    # Optionally send an error message back to the user
                                    await send_whatsapp_message(user_phone_number, "Sorry, I encountered an error trying to process your request.")
                            else:
                                print(f"Received non-text message type: {message_data.get('type')}. Skipping.")
                        else: # No messages in the value
                            print("No messages found in the change value.")
                    # Handle other types of changes/values if necessary (e.g., message status updates)
                    elif value.get("statuses"):
                        print(f"Received a status update: {value.get('statuses')}")
                        # You might want to log message delivery statuses here
                    else:
                        print(f"Change value not a message or status: {value}")


        return Response(content="EVENT_RECEIVED", status_code=200) # Acknowledge receipt of the event

    except Exception as e:
        print(f"Error in WhatsApp webhook handler: {e}")
        # It's crucial to return a 200 OK to WhatsApp, otherwise they might stop sending webhooks.
        # Log the error internally but don't necessarily send a 500 back to WhatsApp.
        return Response(content="Error processing event", status_code=200) # Or 500 if appropriate for your debugging

# --- Main execution (for local development) ---
if __name__ == "__main__":
    import uvicorn
    # Ensure GOOGLE_API_KEY is set before running
    if not GOOGLE_API_KEY:
        print("ERROR: The GOOGLE_API_KEY environment variable is not set.")
        print("Please set it before running the application, e.g.:")
        print("export GOOGLE_API_KEY='your_actual_api_key'")
    else:
        print("GOOGLE_API_KEY found.")

    if WHATSAPP_VERIFY_TOKEN == "YOUR_CHOSEN_VERIFY_TOKEN":
        print("WARNING: WHATSAPP_VERIFY_TOKEN is not set in environment variables. Using default placeholder.")
    if WHATSAPP_ACCESS_TOKEN == "YOUR_WHATSAPP_ACCESS_TOKEN":
        print("WARNING: WHATSAPP_ACCESS_TOKEN is not set in environment variables. Actual sending will be skipped.")
    if WHATSAPP_PHONE_NUMBER_ID == "YOUR_WHATSAPP_PHONE_NUMBER_ID":
        print("WARNING: WHATSAPP_PHONE_NUMBER_ID is not set in environment variables. Actual sending will be impacted.")


    # Create data directory if it doesn't exist, relative to this script
    script_dir = os.path.dirname(os.path.abspath(__file__))
    data_dir_abs = os.path.join(script_dir, CHROMA_DATA_PATH)
    os.makedirs(data_dir_abs, exist_ok=True)
    print(f"ChromaDB data path: {os.path.abspath(data_dir_abs)}")

    print("Starting server...")
    uvicorn.run(app, host="0.0.0.0", port=8000)

# Instructions for running:
# 1. Save this file as `main.py` in the `backend` directory.
# 2. Ensure you have `requirements.txt` in the same directory. (Add `httpx` if not already there)
# 3. Install dependencies: `pip install -r requirements.txt`
# 4. Set your Environment Variables:
#    `export GOOGLE_API_KEY='your_google_api_key'`
#    `export WHATSAPP_VERIFY_TOKEN='your_chosen_verify_token_for_webhook_setup'`
#    `export WHATSAPP_ACCESS_TOKEN='your_whatsapp_business_api_token'`
#    `export WHATSAPP_PHONE_NUMBER_ID='your_whatsapp_business_phone_number_id'`
# 5. Run the server: `python main.py` (or `uvicorn main:app --reload` for development)
#    The server will be available at http://localhost:8000
#    The WhatsApp webhook endpoint will be http://<your_public_ngrok_url>/whatsapp/webhook

# When setting up the webhook with Meta/Twilio, you'll need a publicly accessible URL.
# Use a tool like ngrok (https://ngrok.com/) during development: `./ngrok http 8000`
# Then use the https URL ngrok provides (e.g., https://xxxx-yyy-zzz.ngrok.io/whatsapp/webhook)
# in your WhatsApp API provider's dashboard.
print(f"Current working directory: {os.getcwd()}")
_script_dir = os.path.dirname(os.path.abspath(__file__))
_data_dir_abs = os.path.join(_script_dir, CHROMA_DATA_PATH)
if not os.path.exists(_data_dir_abs):
    print(f"Warning: ChromaDB data directory '{_data_dir_abs}' does not exist. It will be created by ChromaDB if possible, or an error may occur.")
else:
    print(f"ChromaDB data directory '{_data_dir_abs}' confirmed.")
