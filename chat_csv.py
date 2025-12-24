import streamlit as st
import os
import io
from dotenv import load_dotenv

# Google & Pinecone
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

# LangChain
from langchain_community.document_loaders import CSVLoader
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_pinecone import PineconeVectorStore
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_classic.chains import RetrievalQA

st.set_page_config(page_title="EcoChat CSV", page_icon="🌿", layout="wide")

load_dotenv()

# Color Palette used
# #dad7cd (Light Beige) - Main Background
# #a3b18a (Sage) - Sidebar
# #588157 (Fern) - User Bubble / Buttons
# #3a5a40 (Hunter) - Headers
# #344e41 (Dark Green) - Text

st.markdown("""
    <style>
    /* Main Background */
    .stApp {
        background-color: #dad7cd;
        color: #344e41;
    }
    
    /* Sidebar Background */
    [data-testid="stSidebar"] {
        background-color: #a3b18a;
    }
    
    /* Text Colors */
    h1, h2, h3, p, label {
        color: #344e41 !important;
    }
    
    /* Buttons */
    div.stButton > button {
        background-color: #588157;
        color: white !important;
        border-radius: 10px;
        border: none;
    }
    div.stButton > button:hover {
        background-color: #3a5a40;
    }
    
    /* Chat Bubbles */
    .stChatMessage {
        background-color: rgba(255, 255, 255, 0.5);
        border-radius: 15px;
        border: 1px solid #588157;
    }
    </style>
""", unsafe_allow_html=True)

if "messages" not in st.session_state:
    st.session_state.messages = []

if "vector_store" not in st.session_state:
    st.session_state.vector_store = None


@st.cache_resource
def get_embeddings():
    return HuggingFaceEmbeddings(model_name="sentence-transformers/all-mpnet-base-v2")

def download_csv(file_id):
    """Downloads file from Drive to memory"""
    service_account_file = os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE")
    if not service_account_file or not os.path.exists(service_account_file):
        st.error("Service Account JSON not found.")
        return None

    try:
        creds = service_account.Credentials.from_service_account_file(
            service_account_file, scopes=['https://www.googleapis.com/auth/drive']
        )
        service = build('drive', 'v3', credentials=creds)
        request = service.files().get_media(fileId=file_id)
        
        file_stream = io.BytesIO()
        downloader = MediaIoBaseDownload(file_stream, request)
        
        done = False
        while done is False:
            status, done = downloader.next_chunk()
        
        file_stream.seek(0)
        # Save momentarily to disk for CSVLoader (limitation of loader)
        with open("temp_data.csv", "wb") as f:
            f.write(file_stream.read())
            
        return "temp_data.csv"
    except Exception as e:
        st.error(f"Error downloading: {e}")
        return None

def process_data(file_id, new_upload=False):
    """Handles logic for Uploading New vs Connecting to Existing"""
    embeddings = get_embeddings()
    index_name = "csv-chat"
    
    if new_upload:
        with st.spinner("📥 Downloading & Processing CSV..."):
            csv_path = download_csv(file_id)
            if not csv_path: return None
            
            loader = CSVLoader(file_path=csv_path, encoding="utf-8")
            docs = loader.load()
            
            # Create/Overwrite Index in the pinecone
            vectorstore = PineconeVectorStore.from_documents(
                documents=docs, 
                embedding=embeddings, 
                index_name=index_name
            )
            st.success(f"Uploaded {len(docs)} rows to Pinecone!")
            return vectorstore
    else:
        # Connect to existing
        vectorstore = PineconeVectorStore.from_existing_index(
            index_name=index_name,
            embedding=embeddings
        )
        return vectorstore

def get_answer(query, vector_store):
    llm = ChatGoogleGenerativeAI(
        model="gemini-flash-latest",
        temperature=0.3
    )
    
    qa_chain = RetrievalQA.from_chain_type(
        llm=llm,
        chain_type="stuff",
        retriever=vector_store.as_retriever(search_kwargs={"k": 5}),
    )
    
    return qa_chain.invoke({"query": query})['result']

with st.sidebar:
    st.header("⚙️ Data Control")
    st.markdown("---")
    
    mode = st.radio("Choose Mode:", ["Chat with Existing Data", "Upload New File"])
    
    file_id = st.text_input("Google Drive File ID", placeholder="Paste ID here...")
    
    if st.button("🚀 Initialize System"):
        if not os.getenv("PINECONE_API_KEY") or not os.getenv("GOOGLE_API_KEY"):
            st.error("🔑 API Keys missing in .env file!")
        else:
            if mode == "Upload New File":
                if not file_id:
                    st.warning("⚠️ Please enter a File ID.")
                else:
                    st.session_state.vector_store = process_data(file_id, new_upload=True)
            else:
                st.session_state.vector_store = process_data(None, new_upload=False)
                st.success("🔗 Connected to existing Database!")

# --- MAIN CHAT INTERFACE ---
st.title("🌿 EcoChat: Talk to your Data")
st.markdown("Ask questions about your CSV files stored in Google Drive.")

# Chat History
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

if prompt := st.chat_input("Ask a question about your data..."):
    if not st.session_state.vector_store:
        st.error("Please initialize the system from the Sidebar first!")
    else:
        st.chat_message("user").markdown(prompt)
        st.session_state.messages.append({"role": "user", "content": prompt})

        with st.chat_message("assistant"):
            with st.spinner("Thinking..."):
                try:
                    response = get_answer(prompt, st.session_state.vector_store)
                    st.markdown(response)
                    st.session_state.messages.append({"role": "assistant", "content": response})
                except Exception as e:
                    st.error(f"Error: {e}")