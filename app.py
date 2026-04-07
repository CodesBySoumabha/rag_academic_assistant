from flask import Flask, render_template, request, redirect, session, send_from_directory, jsonify
import sqlite3
import os
import fitz
from dotenv import load_dotenv
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash

# --- RAG imports ---
from langchain_community.document_loaders import PyPDFLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_chroma import Chroma
from langchain_groq import ChatGroq

load_dotenv()
import pytesseract
pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'
import pdf2image
pdf2image.pdf2image.POPPLER_PATH = r"C:\poppler\Release-25.12.0-0\poppler-25.12.0\Library\bin"

app = Flask(__name__)
app.secret_key = "noteflow_secret_2024"

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
UPLOAD_FOLDER = os.path.join(BASE_DIR, "uploads")
CHROMA_DIR = os.path.join(BASE_DIR, "chroma_db")

if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)
if not os.path.exists(CHROMA_DIR):
    os.makedirs(CHROMA_DIR)

# --- Embedding model (free, runs locally, no API needed) ---
embeddings = HuggingFaceEmbeddings(
    model_name="all-MiniLM-L6-v2",
    model_kwargs={"device": "cpu"}
)

# --- Groq LLM ---
llm = ChatGroq(
    model="llama-3.1-8b-instant",
    groq_api_key=os.getenv("GROQ_API_KEY"),
    temperature=0.2
)


# ================================================================
# DATABASE
# ================================================================
def init_db():
    conn = sqlite3.connect("database.db")
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS users(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE,
        password TEXT
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS files(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT,
        filename TEXT,
        category TEXT,
        summary TEXT DEFAULT ''
    )""")
    # Add summary column if upgrading from older database
    try:
        c.execute("ALTER TABLE files ADD COLUMN summary TEXT DEFAULT ''")
    except:
        pass
    conn.commit()
    conn.close()

init_db()


# ================================================================
# HELPERS
# ================================================================
def categorize_pdf(filepath):
    try:
        doc = fitz.open(filepath)
        text = doc[0].get_text().lower()
        if "python" in text or "programming" in text or "algorithm" in text:
            return "Programming"
        elif "machine learning" in text or "neural" in text or "deep learning" in text:
            return "AI"
        elif "physics" in text or "quantum" in text or "chemistry" in text:
            return "Science"
        elif "finance" in text or "economy" in text or "market" in text:
            return "Business"
        else:
            return "Others"
    except:
        return "Others"


def index_pdf_to_chroma(filepath, filename, username):
    """Load a text-based PDF, chunk it, embed it, store in ChromaDB."""
    try:
        loader = PyPDFLoader(filepath)
        pages = loader.load()

        splitter = RecursiveCharacterTextSplitter(
            chunk_size=500,
            chunk_overlap=50
        )
        chunks = splitter.split_documents(pages)

        for chunk in chunks:
            chunk.metadata["username"] = username
            chunk.metadata["filename"] = filename

        collection_name = f"user_{username}".replace("-", "_").replace(".", "_")
        vectorstore = Chroma(
            collection_name=collection_name,
            embedding_function=embeddings,
            persist_directory=CHROMA_DIR
        )
        vectorstore.add_documents(chunks)
        print(f"[ChromaDB] Indexed {len(chunks)} chunks for {filename}")
        return True
    except Exception as e:
        print(f"[ChromaDB indexing error] {e}")
        return False


def index_text_to_chroma(text, filename, username):
    """Index plain text (from OCR) into ChromaDB."""
    try:
        splitter = RecursiveCharacterTextSplitter(
            chunk_size=500,
            chunk_overlap=50
        )
        chunks = splitter.create_documents(
            texts=[text],
            metadatas=[{"username": username, "filename": filename, "page": 0}]
        )

        collection_name = f"user_{username}".replace("-", "_").replace(".", "_")
        vectorstore = Chroma(
            collection_name=collection_name,
            embedding_function=embeddings,
            persist_directory=CHROMA_DIR
        )
        vectorstore.add_documents(chunks)
        print(f"[ChromaDB] Indexed {len(chunks)} OCR chunks for {filename}")
        return True
    except Exception as e:
        print(f"[ChromaDB OCR indexing error] {e}")
        return False


def generate_summary(text):
    """Generate a 2-sentence summary using Groq."""
    try:
        snippet = text[:1500]
        response = llm.invoke(
            f"Summarize the following study notes in exactly 2 sentences:\n\n{snippet}"
        )
        return response.content.strip()
    except Exception as e:
        print(f"[Summary error] {e}")
        return ""


def delete_from_chroma(filename, username):
    """Remove all chunks of a file from ChromaDB."""
    try:
        collection_name = f"user_{username}".replace("-", "_").replace(".", "_")
        vectorstore = Chroma(
            collection_name=collection_name,
            embedding_function=embeddings,
            persist_directory=CHROMA_DIR
        )
        results = vectorstore.get(where={"filename": filename})
        if results and results["ids"]:
            vectorstore.delete(ids=results["ids"])
            print(f"[ChromaDB] Deleted chunks for {filename}")
    except Exception as e:
        print(f"[ChromaDB delete error] {e}")


def extract_text_from_pdf(filepath):
    """Extract text from a normal (text-based) PDF using PyMuPDF."""
    try:
        doc = fitz.open(filepath)
        text = ""
        for page in doc:
            text += page.get_text()
        return text.strip()
    except:
        return ""


def is_scanned_pdf(filepath):
    """Returns True if PDF has no extractable text (i.e. it is image-based)."""
    try:
        doc = fitz.open(filepath)
        text = ""
        for page in doc:
            text += page.get_text()
        return len(text.strip()) < 50
    except:
        return False


def ocr_image(filepath):
    """Run Tesseract OCR on a JPG/PNG image file."""
    try:
        import pytesseract
        from PIL import Image
        img = Image.open(filepath)
        text = pytesseract.image_to_string(img)
        return text.strip()
    except Exception as e:
        print(f"[OCR image error] {e}")
        return ""


def ocr_scanned_pdf(filepath):
    """Run Tesseract OCR on every page of a scanned PDF."""
    try:
        import pytesseract
        from pdf2image import convert_from_path
        pages = convert_from_path(filepath, dpi=200, poppler_path=r"C:\poppler\Release-25.12.0-0\poppler-25.12.0\Library\bin")
        pages = convert_from_path(filepath, dpi=200)
        full_text = ""
        for i, page_img in enumerate(pages):
            page_text = pytesseract.image_to_string(page_img)
            full_text += f"\n[Page {i+1}]\n{page_text}"
        return full_text.strip()
    except Exception as e:
        print(f"[OCR scanned PDF error] {e}")
        return ""


# ================================================================
# ROUTES — Auth
# ================================================================
@app.route("/")
def landing():
    return render_template("landing.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]

        conn = sqlite3.connect("database.db")
        c = conn.cursor()
        c.execute("SELECT * FROM users WHERE username=?", (username,))
        user = c.fetchone()
        conn.close()

        if user and check_password_hash(user[2], password):
            session["user"] = username
            return redirect("/dashboard")

    return render_template("login.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form["username"]
        password = generate_password_hash(request.form["password"])

        conn = sqlite3.connect("database.db")
        c = conn.cursor()
        try:
            c.execute("INSERT INTO users(username,password) VALUES (?,?)", (username, password))
            conn.commit()
        except:
            pass
        conn.close()
        return redirect("/login")

    return render_template("register.html")


@app.route("/logout")
def logout():
    session.pop("user", None)
    return redirect("/")


# ================================================================
# ROUTES — Dashboard
# ================================================================
@app.route("/dashboard")
def dashboard():
    if "user" not in session:
        return redirect("/login")

    username = session["user"]
    conn = sqlite3.connect("database.db")
    c = conn.cursor()
    c.execute("SELECT filename, category, summary FROM files WHERE username=?", (username,))
    user_files = c.fetchall()
    c.execute("SELECT username, filename, category FROM files WHERE username != ?", (username,))
    community_files = c.fetchall()
    conn.close()

    categories = {}
    for filename, category, summary in user_files:
        if category not in categories:
            categories[category] = []
        categories[category].append((filename, summary))

    return render_template("dashboard.html", categories=categories, community_files=community_files)


# ================================================================
# ROUTES — Upload (handles PDF + JPG/PNG with OCR)
# ================================================================
@app.route("/upload", methods=["POST"])
def upload():
    if "user" not in session:
        return redirect("/login")

    file = request.files["pdf"]
    if not file or not file.filename:
        return redirect("/dashboard")

    filename = secure_filename(file.filename)
    filepath = os.path.join(UPLOAD_FOLDER, filename)
    file.save(filepath)

    ext = filename.lower().rsplit(".", 1)[-1]
    extracted_text = ""
    category = "Others"

    if ext == "pdf":
        if is_scanned_pdf(filepath):
            # Scanned/image-based PDF — use OCR
            print(f"[Upload] Scanned PDF detected, running OCR: {filename}")
            extracted_text = ocr_scanned_pdf(filepath)
            if extracted_text:
                index_text_to_chroma(extracted_text, filename, session["user"])
        else:
            # Normal text-based PDF — use LangChain loader
            print(f"[Upload] Text PDF detected: {filename}")
            extracted_text = extract_text_from_pdf(filepath)
            index_pdf_to_chroma(filepath, filename, session["user"])

        category = categorize_pdf(filepath)

    elif ext in ["jpg", "jpeg", "png", "webp"]:
        # Image file — run OCR
        print(f"[Upload] Image file, running OCR: {filename}")
        extracted_text = ocr_image(filepath)
        if extracted_text:
            index_text_to_chroma(extracted_text, filename, session["user"])
        category = "Others"

    # Generate summary from extracted text
    summary = generate_summary(extracted_text) if extracted_text else ""

    # Save to database
    conn = sqlite3.connect("database.db")
    c = conn.cursor()
    c.execute(
        "INSERT INTO files(username, filename, category, summary) VALUES (?,?,?,?)",
        (session["user"], filename, category, summary)
    )
    conn.commit()
    conn.close()

    return redirect("/dashboard")


# ================================================================
# ROUTES — Delete
# ================================================================
@app.route("/delete/<filename>")
def delete(filename):
    if "user" not in session:
        return redirect("/login")

    filepath = os.path.join(UPLOAD_FOLDER, filename)
    if os.path.exists(filepath):
        os.remove(filepath)

    delete_from_chroma(filename, session["user"])

    conn = sqlite3.connect("database.db")
    c = conn.cursor()
    c.execute("DELETE FROM files WHERE filename=? AND username=?", (filename, session["user"]))
    conn.commit()
    conn.close()

    return redirect("/dashboard")


# ================================================================
# ROUTES — View
# ================================================================
@app.route("/view/<filename>")
def view_pdf(filename):
    if "user" not in session:
        return redirect("/login")

    conn = sqlite3.connect("database.db")
    c = conn.cursor()
    c.execute("SELECT category FROM files WHERE filename=?", (filename,))
    result = c.fetchone()
    conn.close()

    category = result[0] if result else "Unknown"
    return render_template("viewer.html", filename=filename, category=category)


@app.route("/file/<filename>")
def serve_file(filename):
    if "user" not in session:
        return redirect("/login")
    return send_from_directory(UPLOAD_FOLDER, filename)


# ================================================================
# ROUTES — AI Ask (RAG) — Direct Groq call, no RetrievalQA
# ================================================================
@app.route("/ask", methods=["POST"])
def ask():
    if "user" not in session:
        return jsonify({"error": "Not logged in"}), 401

    data = request.get_json()
    question = data.get("question", "").strip()
    filename = data.get("filename", "").strip()

    if not question:
        return jsonify({"error": "No question provided"}), 400

    try:
        username = session["user"]
        collection_name = f"user_{username}".replace("-", "_").replace(".", "_")

        vectorstore = Chroma(
            collection_name=collection_name,
            embedding_function=embeddings,
            persist_directory=CHROMA_DIR
        )

        # Retrieve relevant chunks — restrict to current file if one is open
        if filename:
            docs = vectorstore.similarity_search(
                question, k=4,
                filter={"filename": filename}
            )
        else:
            docs = vectorstore.similarity_search(question, k=4)

        if not docs:
            return jsonify({
                "answer": "I couldn't find any relevant content in your uploaded notes for this question. Try uploading more notes first.",
                "sources": []
            })

        # Build context from retrieved chunks
        context = "\n\n".join([doc.page_content for doc in docs])

        # Build prompt
        prompt = f"""You are an AI study assistant. Answer the student's question using ONLY the context from their uploaded notes below.
If the answer is not found in the notes, say "I couldn't find this in your uploaded notes."
Always be clear, concise, and educational.

Context from notes:
{context}

Student's question: {question}

Answer:"""

        # Call Groq directly
        response = llm.invoke(prompt)
        answer = response.content.strip()

        # Build source citations
        sources = []
        seen = set()
        for doc in docs:
            src_file = doc.metadata.get("filename", "unknown")
            page = doc.metadata.get("page", 0)
            snippet = doc.page_content[:150].strip().replace("\n", " ")
            key = f"{src_file}_{page}"
            if key not in seen:
                seen.add(key)
                sources.append({
                    "filename": src_file,
                    "page": page + 1,
                    "snippet": snippet
                })

        return jsonify({"answer": answer, "sources": sources})

    except Exception as e:
        print(f"[/ask error] {e}")
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    app.run(debug=True, use_reloader=False)