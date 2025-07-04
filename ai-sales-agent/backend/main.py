import os
import io
from typing import List, Optional

from fastapi import FastAPI, File, UploadFile, Form, HTTPException
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware # Import for CORS

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

# --- Main execution (for local development) ---
if __name__ == "__main__":
    import uvicorn
    # Ensure GOOGLE_API_KEY is set before running
    if not GOOGLE_API_KEY:
        print("ERROR: The GOOGLE_API_KEY environment variable is not set.")
        print("Please set it before running the application, e.g.:")
        print("export GOOGLE_API_KEY='your_actual_api_key'")
    else:
        print("GOOGLE_API_KEY found. Starting server...")

    # Create data directory if it doesn't exist, relative to this script
    script_dir = os.path.dirname(os.path.abspath(__file__))
    data_dir_abs = os.path.join(script_dir, CHROMA_DATA_PATH)
    os.makedirs(data_dir_abs, exist_ok=True)
    print(f"ChromaDB data path: {os.path.abspath(data_dir_abs)}")


    uvicorn.run(app, host="0.0.0.0", port=8000)

# Instructions for running:
# 1. Save this file as `main.py` in the `backend` directory.
# 2. Ensure you have `requirements.txt` in the same directory.
# 3. Install dependencies: `pip install -r requirements.txt`
# 4. Set your Google API Key: `export GOOGLE_API_KEY='your_google_api_key'`
# 5. Run the server: `python main.py` (or `uvicorn main:app --reload` for development)
# The server will be available at http://localhost:8000
# The ChromaDB data will be stored in `../data` relative to `main.py` (i.e., `ai-sales-agent/data`)
# To create the data directory correctly, ensure `ai-sales-agent/data` exists.
# The script now attempts to create this directory if it doesn't exist.
print(f"Current working directory: {os.getcwd()}")
# Adjust CHROMA_DATA_PATH if main.py is run from a different working directory than 'backend'
# For example, if run from 'ai-sales-agent', CHROMA_DATA_PATH should be "./data"
# The current setup assumes `python main.py` is run from within the `backend` directory.
# The `os.path.join(script_dir, CHROMA_DATA_PATH)` should make it robust.
# Final check for data path:
_script_dir = os.path.dirname(os.path.abspath(__file__))
_data_dir_abs = os.path.join(_script_dir, CHROMA_DATA_PATH)
if not os.path.exists(_data_dir_abs):
    print(f"Warning: ChromaDB data directory '{_data_dir_abs}' does not exist. It will be created by ChromaDB if possible, or an error may occur.")
else:
    print(f"ChromaDB data directory '{_data_dir_abs}' confirmed.")
