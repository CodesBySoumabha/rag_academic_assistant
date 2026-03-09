from flask import Flask, render_template, request, redirect, session
import sqlite3
import os
import fitz

app = Flask(__name__)
app.secret_key = "secret123"

UPLOAD_FOLDER = "uploads"

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
@app.route("/", methods=["GET","POST"])
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

        return redirect("/")

    return render_template("register.html")


# DASHBOARD
@app.route("/dashboard", methods=["GET","POST"])
def dashboard():

    if "user" not in session:
        return redirect("/")

    username = session["user"]

    conn = sqlite3.connect("database.db")
    c = conn.cursor()

    c.execute("SELECT filename,category FROM files WHERE username=?",(username,))
    files = c.fetchall()

    conn.close()

    categories = {}

    for file in files:
        cat = file[1]

        if cat not in categories:
            categories[cat] = []

        categories[cat].append(file[0])

    return render_template("dashboard.html",categories=categories)


# UPLOAD PDF
@app.route("/upload", methods=["POST"])
def upload():

    if "user" not in session:
        return redirect("/")

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
        return redirect("/")

    filepath = os.path.join(UPLOAD_FOLDER,filename)

    if os.path.exists(filepath):
        os.remove(filepath)

    conn = sqlite3.connect("database.db")
    c = conn.cursor()

    c.execute("DELETE FROM files WHERE filename=?",(filename,))
    conn.commit()

    conn.close()

    return redirect("/dashboard")


# LOGOUT
@app.route("/logout")
def logout():

    session.pop("user",None)
    return redirect("/")


app.run(debug=True)