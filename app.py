from flask import Flask, render_template, request, redirect, session, send_from_directory
import sqlite3
import os
import fitz

app = Flask(__name__)
app.secret_key = "secret123"

# FIX: Use an absolute path for the uploads folder so Flask never loses track of it
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
UPLOAD_FOLDER = os.path.join(BASE_DIR, "uploads")

if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

# DATABASE INIT
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
        category TEXT
    )""")

    conn.commit()
    conn.close()

init_db()


# AUTO CATEGORIZE PDF
def categorize_pdf(filepath):
    try:
        doc = fitz.open(filepath)
        text = doc[0].get_text().lower()

        if "python" in text or "programming" in text:
            return "Programming"
        elif "machine learning" in text or "ai" in text:
            return "AI"
        elif "physics" in text or "quantum" in text:
            return "Science"
        elif "finance" in text or "economy" in text:
            return "Business"
        else:
            return "Others"
    except:
        return "Others"
    
# LANDING PAGE
@app.route("/")
def landing():
    return render_template("landing.html")

# LOGIN PAGE
@app.route("/login", methods=["GET","POST"])
def login():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]

        conn = sqlite3.connect("database.db")
        c = conn.cursor()

        c.execute("SELECT * FROM users WHERE username=? AND password=?", (username,password))
        user = c.fetchone()

        conn.close()

        if user:
            session["user"] = username
            return redirect("/dashboard")

    return render_template("login.html")


# REGISTER PAGE
@app.route("/register", methods=["GET","POST"])
def register():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]

        conn = sqlite3.connect("database.db")
        c = conn.cursor()

        try:
            c.execute("INSERT INTO users(username,password) VALUES (?,?)",(username,password))
            conn.commit()
        except:
            pass

        conn.close()

        return redirect("/login")

    return render_template("register.html")


# DASHBOARD
@app.route("/dashboard", methods=["GET","POST"])
def dashboard():
    if "user" not in session:
        return redirect("/login")

    username = session["user"]

    conn = sqlite3.connect("database.db")
    c = conn.cursor()

    # 1. Get the current user's files
    c.execute("SELECT filename,category FROM files WHERE username=?",(username,))
    user_files = c.fetchall()

    # 2. Get EVERYONE ELSE'S files (Community Notes)
    c.execute("SELECT username, filename, category FROM files WHERE username != ?", (username,))
    community_files = c.fetchall()

    conn.close()

    # Group the user's files by category
    categories = {}
    for file in user_files:
        cat = file[1]
        if cat not in categories:
            categories[cat] = []
        categories[cat].append(file[0])

    # Pass both sets of files to the template
    return render_template("dashboard.html", categories=categories, community_files=community_files)


# UPLOAD PDF
@app.route("/upload", methods=["POST"])
def upload():
    if "user" not in session:
        return redirect("/login")

    file = request.files["pdf"]

    if file:
        filepath = os.path.join(UPLOAD_FOLDER,file.filename)
        file.save(filepath)

        category = categorize_pdf(filepath)

        conn = sqlite3.connect("database.db")
        c = conn.cursor()

        c.execute("INSERT INTO files(username,filename,category) VALUES (?,?,?)",
        (session["user"],file.filename,category))

        conn.commit()
        conn.close()

    return redirect("/dashboard")


# DELETE FILE
@app.route("/delete/<filename>")
def delete(filename):
    if "user" not in session:
        return redirect("/login")

    filepath = os.path.join(UPLOAD_FOLDER,filename)

    if os.path.exists(filepath):
        os.remove(filepath)

    conn = sqlite3.connect("database.db")
    c = conn.cursor()

    c.execute("DELETE FROM files WHERE filename=?",(filename,))
    conn.commit()

    conn.close()

    return redirect("/dashboard")

# VIEW PDF PAGE (Loads the viewer.html template)
@app.route("/view/<filename>")
def view_pdf(filename):
    if "user" not in session:
        return redirect("/login")

    username = session["user"]
    
    conn = sqlite3.connect("database.db")
    c = conn.cursor()
    c.execute("SELECT category FROM files WHERE username=? AND filename=?", (username, filename))
    result = c.fetchone()
    conn.close()

    category = result[0] if result else "Unknown"

    return render_template("viewer.html", filename=filename, category=category)

# SERVE RAW PDF FILES (This is what the iframe inside viewer.html actually calls!)
@app.route("/file/<filename>")
def serve_file(filename):
    if "user" not in session:
        return redirect("/login")
    return send_from_directory(UPLOAD_FOLDER, filename)


# LOGOUT
@app.route("/logout")
def logout():
    session.pop("user",None)
    return redirect("/")

if __name__ == "__main__":
    app.run(debug=True)