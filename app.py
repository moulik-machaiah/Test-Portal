from flask import Flask, render_template, request, redirect, session, send_from_directory
import psycopg2
import os
import uuid
from werkzeug.utils import secure_filename
from psycopg2.extras import RealDictCursor

app = Flask(__name__)
app.secret_key = "secret_key_change_in_production"


UPLOAD_DIR = os.path.join(os.path.dirname(__file__), "static", "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

ALLOWED_EXT = {"png", "jpg", "jpeg", "gif", "webp"}
ALLOWED_PDF_EXT = {"pdf"}

def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXT


def save_upload(file_field):
    """Save an uploaded image; return relative path or None."""
    f = request.files.get(file_field)
    if f and f.filename and allowed_file(f.filename):
        ext = f.filename.rsplit(".", 1)[1].lower()
        name = f"{uuid.uuid4().hex}.{ext}"
        f.save(os.path.join(UPLOAD_DIR, name))
        return f"uploads/{name}"
    return None

def allowed_pdf(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_PDF_EXT

def save_pdf_upload(file_field):
    """Save an uploaded PDF answer; return relative path or None."""
    f = request.files.get(file_field)
    if f and f.filename and allowed_pdf(f.filename):
        name = f"{uuid.uuid4().hex}.pdf"
        f.save(os.path.join(UPLOAD_DIR, name))
        return f"uploads/{name}"
    return None

def get_db():
    return psycopg2.connect(
        os.environ.get("DATABASE_URL"),
        cursor_factory=RealDictCursor
    )

def init_db():
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS users(
    id SERIAL PRIMARY KEY,
    username TEXT,
    password TEXT,
    role TEXT,
    name TEXT,
    roll TEXT,
    course TEXT,
    phone TEXT,
    photo TEXT
    );
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS exams(
    id SERIAL PRIMARY KEY,
    title TEXT,
    duration INTEGER,
    results_published INTEGER DEFAULT 0
    );
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS questions(
    id SERIAL PRIMARY KEY,
    exam_id INTEGER,
    question TEXT,
    type TEXT,
    marks INTEGER,
    correct_answer TEXT,
    option_a TEXT,
    option_b TEXT,
    option_c TEXT,
    option_d TEXT,
    question_image TEXT,
    option_a_image TEXT,
    option_b_image TEXT,
    option_c_image TEXT,
    option_d_image TEXT
    );
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS responses(
    id SERIAL PRIMARY KEY,
    student TEXT,
    question_id INTEGER,
    answer TEXT,
    marks INTEGER
    );
    """)

    # create admin if not exists
    cur.execute("""
    INSERT INTO users(username,password,role,name)
    SELECT 'Moulik','admin','admin','Admin'
    WHERE NOT EXISTS (
        SELECT 1 FROM users WHERE username='admin'
    );
    """)

    conn.commit()
    conn.close()


def login_required(role=None):
    def decorator(f):
        from functools import wraps
        @wraps(f)
        def wrapper(*args, **kwargs):
            if "user" not in session:
                return redirect("/")
            if role and session.get("role") != role:
                return redirect("/")
            return f(*args, **kwargs)
        return wrapper
    return decorator
    


# ── LOGIN ──────────────────────────────────────────────────────────────────
init_db()

@app.route("/", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()
        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM users WHERE username=%s AND password=%s",
            (username, password)
        )
        user = cur.fetchone()
        conn.close()
        if user:
            session["user"] = user["username"]
            session["role"] = user["role"]
            return redirect("/admin" if user["role"] == "admin" else "/student/exams")
        error = "Invalid username or password."
    return render_template("login.html", error=error)


@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")


# ── ADMIN ──────────────────────────────────────────────────────────────────

@app.route("/admin")
@login_required(role="admin")
def admin():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM exams ORDER BY id DESC")
    exams = cur.fetchall()
    cur.execute("SELECT * FROM users WHERE role='student' ORDER BY name")
    students = cur.fetchall()
    conn.close()
    return render_template("admin.html", exams=exams, students=students, user=session["user"])

@app.route("/student/profile")
@login_required(role="student")
def student_profile():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
         SELECT name, roll, course, phone, photo
         FROM users WHERE username=%s
    """, (session["user"],))
    user = cur.fetchone()
    conn.close()

    user_data = {
        "name": user["name"],
        "roll": user["roll"],
        "course": user["course"],
        "phone": user["phone"],
        "photo": user["photo"]
    }

    return render_template("student_profile.html", user_data=user_data)

@app.route("/add_student", methods=["GET", "POST"])
@login_required(role="admin")
def add_student():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]
        name = request.form["name"]
        roll = request.form["roll"]
        course = request.form["course"]
        phone = request.form["phone"]

        photo_path = save_upload("photo")

        conn = get_db()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO users(username, password, role, name, roll, course, phone, photo)
            VALUES (%s, %s, 'student', %s, %s, %s, %s, %s)
        """, (username, password, name, roll, course, phone, photo_path))
        conn.commit()
        conn.close()

        return redirect("/admin")

    return render_template("add_student.html", user=session["user"])

@app.route("/delete_student/<int:student_id>", methods=["POST"])
@login_required(role="admin")
def delete_student(student_id):
    conn = get_db()
    cur = conn.cursor()
    # Delete their responses first (FK integrity)
    cur.execute("""
        DELETE FROM responses WHERE student = (
            SELECT username FROM users WHERE id=%s
        )
    """, (student_id,))
    cur.execute("DELETE FROM users WHERE id=%s AND role='student'", (student_id,))
    conn.commit()
    conn.close()
    return redirect("/admin")

@app.route("/create_exam", methods=["POST"])
@login_required(role="admin")
def create_exam():
    title    = request.form.get("title", "").strip()
    duration = request.form.get("duration", "").strip()
    if not title or not duration:
        return redirect("/admin")
    conn = get_db()
    cur = conn.cursor()
    cur.execute("INSERT INTO exams(title, duration) VALUES (%s, %s)", (title, int(duration)))
    conn.commit()
    conn.close()
    return redirect("/admin")

@app.route("/delete_exam/<int:exam_id>", methods=["POST"])
@login_required(role="admin")
def delete_exam(exam_id):
    conn = get_db()
    cur = conn.cursor()
    # Delete responses for all questions in this exam
    cur.execute("""
        DELETE FROM responses WHERE question_id IN (
            SELECT id FROM questions WHERE exam_id=%s
        )
    """, (exam_id,))
    # Delete questions
    cur.execute("DELETE FROM questions WHERE exam_id=%s", (exam_id,))
    # Delete the exam
    cur.execute("DELETE FROM exams WHERE id=%s", (exam_id,))
    conn.commit()
    conn.close()
    return redirect("/admin")

@app.route("/add_question", methods=["GET", "POST"])
@login_required(role="admin")
def add_question():
    conn  = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM exams ORDER BY id DESC")
    exams = cur.fetchall()
    if request.method == "POST":
        exam_id  = request.form.get("exam_id")
        question = request.form.get("question", "").strip()
        qtype    = request.form.get("type")
        marks    = request.form.get("marks", "1")
        correct  = request.form.get("correct", "").strip()

        option_a = request.form.get("option_a", "").strip()
        option_b = request.form.get("option_b", "").strip()
        option_c = request.form.get("option_c", "").strip()
        option_d = request.form.get("option_d", "").strip()

        # Image uploads
        question_image = save_upload("question_image")
        option_a_image = save_upload("option_a_image")
        option_b_image = save_upload("option_b_image")
        option_c_image = save_upload("option_c_image")
        option_d_image = save_upload("option_d_image")

        if not exam_id or not qtype:
            conn.close()
            return render_template("add_question.html", exams=exams,
                                   error="Please fill all required fields.",
                                   user=session["user"])
        if not question and not question_image:
            conn.close()
            return render_template("add_question.html", exams=exams,
                                   error="Provide either question text or an image.",
                                   user=session["user"])

        cur = conn.cursor()
        cur.execute("""
            INSERT INTO questions(exam_id, question, type, marks, correct_answer,
                                  option_a, option_b, option_c, option_d,
                                  question_image, option_a_image, option_b_image,
                                  option_c_image, option_d_image)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (exam_id, question, qtype, int(marks), correct,
              option_a, option_b, option_c, option_d,
              question_image, option_a_image, option_b_image,
              option_c_image, option_d_image))
        conn.commit()

        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM questions WHERE exam_id=%s ORDER BY id", (exam_id,)
        )
        questions = cur.fetchall()
        conn.close()
        return render_template("add_question.html", exams=exams, questions=questions,
                               success=True, selected_exam=int(exam_id),
                               user=session["user"])

    selected_exam = request.args.get("exam_id")
    questions = []
    if selected_exam:
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM questions WHERE exam_id=%s ORDER BY id", (selected_exam,)
        )
        questions = cur.fetchall()
    conn.close()
    return render_template("add_question.html", exams=exams, questions=questions,
                           selected_exam=int(selected_exam) if selected_exam else None,
                           user=session["user"])


@app.route("/delete_question/<int:qid>", methods=["POST"])
@login_required(role="admin")
def delete_question(qid):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("DELETE FROM questions WHERE id=%s", (qid,))
    conn.commit()
    conn.close()
    exam_id = request.form.get("exam_id")
    return redirect(f"/add_question?exam_id={exam_id}")


# ── VIEW RESPONSES & GRADING ───────────────────────────────────────────────

@app.route("/view_responses")
@login_required(role="admin")
def view_responses():
    conn  = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM exams ORDER BY id DESC")
    exams = cur.fetchall()

    selected_exam_id = request.args.get("exam_id", type=int)
    selected_student = request.args.get("student")

    students = []
    student_data = []
    exam_obj = None

    if selected_exam_id:
        cur = conn.cursor()
        cur.execute("SELECT * FROM exams WHERE id=%s", (selected_exam_id,))
        exam_obj = cur.fetchone()
        # Students who submitted this exam
        cur = conn.cursor()
        cur.execute("""
            SELECT DISTINCT r.student
            FROM responses r
            JOIN questions q ON r.question_id = q.id
            WHERE q.exam_id = %s
            ORDER BY r.student
        """, (selected_exam_id,))
        students = cur.fetchall()

        if selected_student:
            cur = conn.cursor()
            cur.execute("""
                SELECT r.id as resp_id, r.student, q.question, q.question_image,
                       q.type, q.option_a, q.option_b, q.option_c, q.option_d,
                       q.option_a_image, q.option_b_image, q.option_c_image, q.option_d_image,
                       r.answer, r.marks, q.correct_answer, q.marks as max_marks
                FROM responses r
                JOIN questions q ON r.question_id = q.id
                WHERE q.exam_id = %s AND r.student = %s
                ORDER BY q.id
            """, (selected_exam_id, selected_student))
            student_data = cur.fetchall()

    conn.close()
    return render_template("view_responses.html",
                           exams=exams,
                           selected_exam_id=selected_exam_id,
                           exam_obj=exam_obj,
                           students=students,
                           selected_student=selected_student,
                           student_data=student_data,
                           user=session["user"])


@app.route("/grade", methods=["POST"])
@login_required(role="admin")
def grade():
    resp_id  = request.form.get("resp_id", type=int)
    marks    = request.form.get("marks", type=int, default=0)
    exam_id  = request.form.get("exam_id")
    student  = request.form.get("student")
    conn = get_db()
    cur = conn.cursor()
    cur.execute("UPDATE responses SET marks=%s WHERE id=%s", (marks, resp_id))
    conn.commit()
    conn.close()
    return redirect(f"/view_responses?exam_id={exam_id}&student={student}")


@app.route("/publish_results/<int:exam_id>", methods=["POST"])
@login_required(role="admin")
def publish_results(exam_id):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("UPDATE exams SET results_published=1 WHERE id=%s", (exam_id,))
    conn.commit()
    conn.close()
    return redirect(f"/view_responses?exam_id={exam_id}")


# ── STUDENT ────────────────────────────────────────────────────────────────

@app.route("/student")
@login_required(role="student")
def student_root():
    return redirect("/student/exams")


@app.route("/student/exams")
@login_required(role="student")
def student_exams():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM exams ORDER BY id DESC")
    exams = cur.fetchall()
    cur = conn.cursor()
    cur.execute(
        "SELECT DISTINCT q.exam_id FROM responses r JOIN questions q ON r.question_id=q.id WHERE r.student=%s",
        (session["user"],)
    )
    submitted = cur.fetchall()
    submitted_ids = {row["exam_id"] for row in submitted}
    conn.close()
    return render_template("student_exams.html", exams=exams, submitted_ids=submitted_ids,
                           user=session["user"], tab="exams")


@app.route("/student/results")
@login_required(role="student")
def student_results():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM exams ORDER BY id DESC")
    exams = cur.fetchall()
    cur = conn.cursor()
    cur.execute(
        "SELECT DISTINCT q.exam_id FROM responses r JOIN questions q ON r.question_id=q.id WHERE r.student=%s",
        (session["user"],)
    )
    submitted = cur.fetchall()
    submitted_ids = {row["exam_id"] for row in submitted}

    scores = {}
    for e in exams:
        if e["id"] in submitted_ids:
            cur = conn.cursor()
            cur.execute(
                "SELECT SUM(r.marks) as total, SUM(q.marks) as possible "
                "FROM responses r JOIN questions q ON r.question_id=q.id "
                "WHERE q.exam_id=%s AND r.student=%s",
                (e["id"], session["user"])
            )
            row = cur.fetchone()
            scores[e["id"]] = (row["total"] or 0, row["possible"] or 0)

    conn.close()
    return render_template("student_results.html", exams=exams, submitted_ids=submitted_ids,
                           scores=scores, user=session["user"], tab="results")


@app.route("/instructions/<int:exam_id>")
@login_required(role="student")
def instructions(exam_id):
    conn  = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM exams WHERE id=%s", (exam_id,))
    exam  = cur.fetchone()
    conn.close()
    if not exam:
        return redirect("/student/exams")
    return render_template("instructions.html", exam=exam, user=session["user"])


@app.route("/exam/<int:exam_id>")
@login_required(role="student")
def exam(exam_id):
    conn      = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM exams WHERE id=%s", (exam_id,))
    exam_row  = cur.fetchone()
    cur = conn.cursor()
    cur.execute(
        "SELECT * FROM questions WHERE exam_id=%s ORDER BY id", (exam_id,)
    )
    questions = cur.fetchall()
    conn.close()
    if not exam_row:
        return redirect("/student/exams")
    return render_template("exam.html", questions=questions,
                           duration=exam_row["duration"], exam=exam_row,
                           user=session["user"])


@app.route("/submit/<int:exam_id>", methods=["POST"])
@login_required(role="student")
def submit(exam_id):
    conn    = get_db()
    student = session["user"]

    cur = conn.cursor()
    cur.execute("""
        SELECT 1 FROM responses r
        JOIN questions q ON r.question_id=q.id
        WHERE q.exam_id=%s AND r.student=%s
    """, (exam_id, student))
    already = cur.fetchone()
    if already:
        conn.close()
        return redirect("/student/exams")

    cur = conn.cursor()
    cur.execute(
        "SELECT * FROM questions WHERE exam_id=%s", (exam_id,)
    )
    questions = cur.fetchall()

    for q in questions:
        qid     = q["id"]
        correct = q["correct_answer"]
        marks   = q["marks"]
        qtype   = q["type"]
        ans     = request.form.get(f"q{qid}", "").strip()
        score   = 0
        if qtype == "subjective":
        # Check for PDF upload first; fall back to text answer
            pdf_path = save_pdf_upload(f"pdf_{qid}")
            if pdf_path:
                ans = pdf_path  # store the path as the answer
        elif qtype == "mcq" and ans == correct:
            score = int(marks)

        cur = conn.cursor()
        cur.execute(
            "INSERT INTO responses(student, question_id, answer, marks) VALUES (%s,%s,%s,%s)",
            (student, qid, ans, score)
        )
        
        if qtype == "mcq" and ans == correct:
            score = int(marks)
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO responses(student, question_id, answer, marks) VALUES (%s,%s,%s,%s)",
            (student, qid, ans, score)
        )

    conn.commit()
    conn.close()
    return render_template("result.html", user=session["user"])
