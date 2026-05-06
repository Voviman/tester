import datetime
import hashlib
import json
import random
import sqlite3
import sys
import time
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk


DB_PATH = Path(__file__).parent / "testing_app.db"
DEFAULT_ADMIN_USERNAME = "admin"
DEFAULT_ADMIN_PASSWORD = "admin123"
MAX_VIOLATIONS = 5
DEFAULT_PASSING_PERCENT = 60.0
DEFAULT_TEST_DURATION_SECONDS = 900


def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


def _show_dialog_front(dialog_function, parent, title: str, message: str):
    kwargs = {}
    parent_exists = False
    original_topmost = None

    if parent is not None:
        try:
            parent_exists = bool(parent.winfo_exists())
        except tk.TclError:
            parent_exists = False

    if parent_exists:
        kwargs["parent"] = parent
        try:
            original_topmost = bool(parent.attributes("-topmost"))
            parent.attributes("-topmost", True)
            parent.lift()
            parent.focus_force()
        except tk.TclError:
            pass

    result = dialog_function(title, message, **kwargs)

    if parent_exists and original_topmost is not None:
        try:
            parent.attributes("-topmost", original_topmost)
        except tk.TclError:
            pass

    return result


def show_error(parent, title: str, message: str):
    return _show_dialog_front(messagebox.showerror, parent, title, message)


def show_warning(parent, title: str, message: str):
    return _show_dialog_front(messagebox.showwarning, parent, title, message)


def show_info(parent, title: str, message: str):
    return _show_dialog_front(messagebox.showinfo, parent, title, message)


class DatabaseManager:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._initialize()

    def _connect(self):
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self):
        with self._connect() as connection:
            cursor = connection.cursor()
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS admins (
                    username TEXT PRIMARY KEY,
                    password_hash TEXT NOT NULL
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS topics (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT UNIQUE NOT NULL
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS levels (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT UNIQUE NOT NULL
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS questions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    topic_id INTEGER NOT NULL,
                    level_id INTEGER NOT NULL,
                    question_text TEXT NOT NULL,
                    options_json TEXT NOT NULL,
                    correct_index INTEGER NOT NULL,
                    FOREIGN KEY(topic_id) REFERENCES topics(id),
                    FOREIGN KEY(level_id) REFERENCES levels(id)
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS attempts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_name TEXT NOT NULL,
                    topic_name TEXT NOT NULL,
                    level_name TEXT NOT NULL,
                    score INTEGER NOT NULL,
                    total_questions INTEGER NOT NULL,
                    passed INTEGER NOT NULL,
                    violations INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    ended_at TEXT NOT NULL
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS test_rules (
                    topic_id INTEGER NOT NULL,
                    level_id INTEGER NOT NULL,
                    duration_seconds INTEGER NOT NULL,
                    passing_percent REAL NOT NULL,
                    PRIMARY KEY (topic_id, level_id),
                    FOREIGN KEY(topic_id) REFERENCES topics(id),
                    FOREIGN KEY(level_id) REFERENCES levels(id)
                )
                """
            )

            cursor.execute("SELECT COUNT(*) AS count FROM admins")
            admin_count = cursor.fetchone()["count"]
            if admin_count == 0:
                cursor.execute(
                    "INSERT INTO admins (username, password_hash) VALUES (?, ?)",
                    (DEFAULT_ADMIN_USERNAME, hash_password(DEFAULT_ADMIN_PASSWORD)),
                )

            cursor.execute("SELECT COUNT(*) AS count FROM levels")
            level_count = cursor.fetchone()["count"]
            if level_count == 0:
                for level_name in ["Beginner", "Intermediate", "Advanced"]:
                    cursor.execute("INSERT INTO levels (name) VALUES (?)", (level_name,))

            connection.commit()

    def validate_admin(self, username: str, password: str) -> bool:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT password_hash FROM admins WHERE username = ?",
                (username.strip(),),
            ).fetchone()
            if row is None:
                return False
            return row["password_hash"] == hash_password(password)

    def add_topic(self, topic_name: str):
        with self._connect() as connection:
            connection.execute("INSERT INTO topics (name) VALUES (?)", (topic_name.strip(),))
            connection.commit()

    def add_level(self, level_name: str):
        with self._connect() as connection:
            connection.execute("INSERT INTO levels (name) VALUES (?)", (level_name.strip(),))
            connection.commit()

    def get_topics(self):
        with self._connect() as connection:
            rows = connection.execute("SELECT id, name FROM topics ORDER BY name").fetchall()
        return [dict(row) for row in rows]

    def get_levels(self):
        with self._connect() as connection:
            rows = connection.execute("SELECT id, name FROM levels ORDER BY name").fetchall()
        return [dict(row) for row in rows]

    def get_levels_for_topic(self, topic_id: int):
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT DISTINCT l.id, l.name
                FROM levels l
                JOIN questions q ON q.level_id = l.id
                WHERE q.topic_id = ?
                ORDER BY l.name
                """,
                (topic_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def add_question(
        self,
        topic_id: int,
        level_id: int,
        question_text: str,
        options: list[str],
        correct_index: int,
    ):
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO questions (topic_id, level_id, question_text, options_json, correct_index)
                VALUES (?, ?, ?, ?, ?)
                """,
                (topic_id, level_id, question_text.strip(), json.dumps(options), correct_index),
            )
            connection.commit()

    def get_questions(self, topic_id: int, level_id: int):
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT id, question_text, options_json, correct_index
                FROM questions
                WHERE topic_id = ? AND level_id = ?
                """,
                (topic_id, level_id),
            ).fetchall()
        questions = []
        for row in rows:
            questions.append(
                {
                    "id": row["id"],
                    "question_text": row["question_text"],
                    "options": json.loads(row["options_json"]),
                    "correct_index": row["correct_index"],
                }
            )
        return questions

    def get_question_overview(self):
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT t.name AS topic_name, l.name AS level_name, COUNT(q.id) AS total_questions
                FROM questions q
                JOIN topics t ON t.id = q.topic_id
                JOIN levels l ON l.id = q.level_id
                GROUP BY t.name, l.name
                ORDER BY t.name, l.name
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def get_test_rule(self, topic_id: int, level_id: int):
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT duration_seconds, passing_percent
                FROM test_rules
                WHERE topic_id = ? AND level_id = ?
                """,
                (topic_id, level_id),
            ).fetchone()
        if row is None:
            return {
                "duration_seconds": DEFAULT_TEST_DURATION_SECONDS,
                "passing_percent": DEFAULT_PASSING_PERCENT,
            }
        return dict(row)

    def save_test_rule(
        self,
        topic_id: int,
        level_id: int,
        duration_seconds: int,
        passing_percent: float,
    ):
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO test_rules (topic_id, level_id, duration_seconds, passing_percent)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(topic_id, level_id)
                DO UPDATE SET
                    duration_seconds = excluded.duration_seconds,
                    passing_percent = excluded.passing_percent
                """,
                (topic_id, level_id, duration_seconds, passing_percent),
            )
            connection.commit()

    def save_attempt(
        self,
        user_name: str,
        topic_name: str,
        level_name: str,
        score: int,
        total_questions: int,
        passed: bool,
        violations: int,
        status: str,
        started_at: str,
        ended_at: str,
    ):
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO attempts (
                    user_name, topic_name, level_name, score, total_questions, passed,
                    violations, status, started_at, ended_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    user_name,
                    topic_name,
                    level_name,
                    score,
                    total_questions,
                    int(passed),
                    violations,
                    status,
                    started_at,
                    ended_at,
                ),
            )
            connection.commit()

    def get_attempts(self):
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT user_name, topic_name, level_name, score, total_questions, passed,
                       violations, status, started_at, ended_at
                FROM attempts
                ORDER BY id DESC
                """
            ).fetchall()
        return [dict(row) for row in rows]


class AdminLoginWindow:
    def __init__(self, parent: tk.Tk, db: DatabaseManager):
        self.parent = parent
        self.db = db
        self.window = tk.Toplevel(parent)
        self.window.title("Admin Login")
        self.window.geometry("350x220")
        self.window.resizable(False, False)
        self.window.transient(parent)
        self.window.grab_set()

        container = ttk.Frame(self.window, padding=20)
        container.pack(fill="both", expand=True)

        ttk.Label(container, text="Username").pack(anchor="w")
        self.username_entry = ttk.Entry(container)
        self.username_entry.pack(fill="x", pady=(0, 10))

        ttk.Label(container, text="Password").pack(anchor="w")
        self.password_entry = ttk.Entry(container, show="*")
        self.password_entry.pack(fill="x", pady=(0, 15))
        self.password_entry.bind("<Return>", self._login)

        ttk.Button(container, text="Login", command=self._login).pack(fill="x")
        ttk.Label(
            container,
            text=f"Default admin: {DEFAULT_ADMIN_USERNAME}/{DEFAULT_ADMIN_PASSWORD}",
        ).pack(anchor="w", pady=(12, 0))

        self.username_entry.focus_set()

    def _login(self, _event=None):
        username = self.username_entry.get().strip()
        password = self.password_entry.get()
        if not username or not password:
            show_error(self.window, "Login Error", "Enter username and password.")
            return
        if self.db.validate_admin(username, password):
            self.window.destroy()
            AdminPanelWindow(self.parent, self.db)
        else:
            show_error(self.window, "Login Error", "Invalid username or password.")


class AdminPanelWindow:
    def __init__(self, parent: tk.Tk, db: DatabaseManager):
        self.parent = parent
        self.db = db
        self.window = tk.Toplevel(parent)
        self.window.title("Admin Panel")
        self.window.geometry("950x650")

        notebook = ttk.Notebook(self.window)
        notebook.pack(fill="both", expand=True, padx=10, pady=10)

        self.results_tab = ttk.Frame(notebook)
        self.catalog_tab = ttk.Frame(notebook)
        self.questions_tab = ttk.Frame(notebook)

        notebook.add(self.results_tab, text="Results")
        notebook.add(self.catalog_tab, text="Topics & Levels")
        notebook.add(self.questions_tab, text="Questions")

        self._build_results_tab()
        self._build_catalog_tab()
        self._build_questions_tab()

        self.refresh_results()
        self.refresh_topics_levels()
        self.refresh_question_overview()

    def _build_results_tab(self):
        columns = (
            "user",
            "topic",
            "level",
            "score",
            "passed",
            "violations",
            "status",
            "started",
            "ended",
        )
        self.results_tree = ttk.Treeview(
            self.results_tab, columns=columns, show="headings", height=20
        )
        headings = {
            "user": "User",
            "topic": "Topic",
            "level": "Level",
            "score": "Score",
            "passed": "Passed",
            "violations": "Violations",
            "status": "Status",
            "started": "Started",
            "ended": "Ended",
        }
        for column in columns:
            self.results_tree.heading(column, text=headings[column])
            self.results_tree.column(column, width=100, anchor="center")
        self.results_tree.column("status", width=170, anchor="center")
        self.results_tree.column("started", width=150, anchor="center")
        self.results_tree.column("ended", width=150, anchor="center")
        self.results_tree.pack(fill="both", expand=True, padx=8, pady=8)

        ttk.Button(
            self.results_tab, text="Refresh Results", command=self.refresh_results
        ).pack(anchor="e", padx=8, pady=(0, 8))

    def _build_catalog_tab(self):
        main = ttk.Frame(self.catalog_tab, padding=12)
        main.pack(fill="both", expand=True)

        topic_frame = ttk.LabelFrame(main, text="Add Topic", padding=10)
        topic_frame.pack(fill="x", pady=(0, 10))
        self.topic_entry = ttk.Entry(topic_frame)
        self.topic_entry.pack(side="left", fill="x", expand=True)
        ttk.Button(topic_frame, text="Add", command=self._add_topic).pack(
            side="left", padx=(8, 0)
        )

        level_frame = ttk.LabelFrame(main, text="Add Level", padding=10)
        level_frame.pack(fill="x", pady=(0, 14))
        self.level_entry = ttk.Entry(level_frame)
        self.level_entry.pack(side="left", fill="x", expand=True)
        ttk.Button(level_frame, text="Add", command=self._add_level).pack(
            side="left", padx=(8, 0)
        )

        lists_frame = ttk.Frame(main)
        lists_frame.pack(fill="both", expand=True)

        topic_list_frame = ttk.LabelFrame(lists_frame, text="Topics", padding=10)
        topic_list_frame.pack(side="left", fill="both", expand=True, padx=(0, 6))
        self.topic_listbox = tk.Listbox(topic_list_frame, height=12)
        self.topic_listbox.pack(fill="both", expand=True)

        level_list_frame = ttk.LabelFrame(lists_frame, text="Levels", padding=10)
        level_list_frame.pack(side="left", fill="both", expand=True, padx=(6, 0))
        self.level_listbox = tk.Listbox(level_list_frame, height=12)
        self.level_listbox.pack(fill="both", expand=True)

    def _build_questions_tab(self):
        main = ttk.Frame(self.questions_tab, padding=12)
        main.pack(fill="both", expand=True)

        top_row = ttk.Frame(main)
        top_row.pack(fill="x")

        ttk.Label(top_row, text="Topic").grid(row=0, column=0, sticky="w", padx=(0, 8))
        self.topic_combo = ttk.Combobox(top_row, state="readonly")
        self.topic_combo.grid(row=0, column=1, sticky="ew", padx=(0, 16))
        self.topic_combo.bind("<<ComboboxSelected>>", self._on_rule_selection_change)

        ttk.Label(top_row, text="Level").grid(row=0, column=2, sticky="w", padx=(0, 8))
        self.level_combo = ttk.Combobox(top_row, state="readonly")
        self.level_combo.grid(row=0, column=3, sticky="ew")
        self.level_combo.bind("<<ComboboxSelected>>", self._on_rule_selection_change)

        top_row.columnconfigure(1, weight=1)
        top_row.columnconfigure(3, weight=1)

        question_frame = ttk.LabelFrame(main, text="Question Editor", padding=10)
        question_frame.pack(fill="x", pady=(12, 8))

        ttk.Label(question_frame, text="Question text").grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(0, 4)
        )
        self.question_text = tk.Text(question_frame, height=4, wrap="word")
        self.question_text.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(0, 10))

        self.option_entries = []
        for idx in range(4):
            ttk.Label(question_frame, text=f"Option {idx + 1}").grid(
                row=idx + 2, column=0, sticky="w", pady=2
            )
            entry = ttk.Entry(question_frame)
            entry.grid(row=idx + 2, column=1, sticky="ew", pady=2, padx=(8, 0))
            self.option_entries.append(entry)

        ttk.Label(question_frame, text="Correct option").grid(
            row=6, column=0, sticky="w", pady=(10, 2)
        )
        self.correct_option_combo = ttk.Combobox(
            question_frame, values=["1", "2", "3", "4"], state="readonly", width=6
        )
        self.correct_option_combo.grid(row=6, column=1, sticky="w", pady=(10, 2))
        self.correct_option_combo.set("1")

        ttk.Button(question_frame, text="Add Question", command=self._add_question).grid(
            row=7, column=0, columnspan=2, sticky="ew", pady=(12, 0)
        )
        question_frame.columnconfigure(1, weight=1)

        rules_frame = ttk.LabelFrame(main, text="Test Rules (Per Topic + Level)", padding=10)
        rules_frame.pack(fill="x", pady=(0, 8))

        ttk.Label(rules_frame, text="Duration (minutes)").grid(row=0, column=0, sticky="w")
        self.duration_entry = ttk.Entry(rules_frame, width=12)
        self.duration_entry.grid(row=0, column=1, sticky="w", padx=(8, 18))

        ttk.Label(rules_frame, text="Passing percent").grid(row=0, column=2, sticky="w")
        self.passing_percent_entry = ttk.Entry(rules_frame, width=12)
        self.passing_percent_entry.grid(row=0, column=3, sticky="w", padx=(8, 18))

        ttk.Button(rules_frame, text="Save Rules", command=self._save_test_rule).grid(
            row=0, column=4, sticky="w"
        )

        overview_frame = ttk.LabelFrame(main, text="Question Counts", padding=8)
        overview_frame.pack(fill="both", expand=True, pady=(8, 0))

        columns = ("topic", "level", "count")
        self.overview_tree = ttk.Treeview(
            overview_frame, columns=columns, show="headings", height=8
        )
        self.overview_tree.heading("topic", text="Topic")
        self.overview_tree.heading("level", text="Level")
        self.overview_tree.heading("count", text="Questions")
        self.overview_tree.column("topic", width=220, anchor="w")
        self.overview_tree.column("level", width=220, anchor="w")
        self.overview_tree.column("count", width=120, anchor="center")
        self.overview_tree.pack(fill="both", expand=True)

        ttk.Button(
            main, text="Refresh Question Counts", command=self.refresh_question_overview
        ).pack(anchor="e", pady=(8, 0))

    def refresh_results(self):
        for item in self.results_tree.get_children():
            self.results_tree.delete(item)
        for attempt in self.db.get_attempts():
            passed = "Yes" if attempt["passed"] else "No"
            score_text = f'{attempt["score"]}/{attempt["total_questions"]}'
            self.results_tree.insert(
                "",
                "end",
                values=(
                    attempt["user_name"],
                    attempt["topic_name"],
                    attempt["level_name"],
                    score_text,
                    passed,
                    attempt["violations"],
                    attempt["status"],
                    attempt["started_at"],
                    attempt["ended_at"],
                ),
            )

    def refresh_topics_levels(self):
        topics = self.db.get_topics()
        levels = self.db.get_levels()

        self.topic_listbox.delete(0, tk.END)
        for topic in topics:
            self.topic_listbox.insert(tk.END, topic["name"])

        self.level_listbox.delete(0, tk.END)
        for level in levels:
            self.level_listbox.insert(tk.END, level["name"])

        topic_options = [f'{topic["id"]}: {topic["name"]}' for topic in topics]
        level_options = [f'{level["id"]}: {level["name"]}' for level in levels]
        self.topic_combo["values"] = topic_options
        self.level_combo["values"] = level_options
        if topic_options and not self.topic_combo.get():
            self.topic_combo.set(topic_options[0])
        if level_options and not self.level_combo.get():
            self.level_combo.set(level_options[0])
        self._load_test_rule_into_form()

    def refresh_question_overview(self):
        for item in self.overview_tree.get_children():
            self.overview_tree.delete(item)
        for row in self.db.get_question_overview():
            self.overview_tree.insert(
                "",
                "end",
                values=(row["topic_name"], row["level_name"], row["total_questions"]),
            )

    def _add_topic(self):
        topic_name = self.topic_entry.get().strip()
        if not topic_name:
            show_error(self.window, "Validation Error", "Topic name is required.")
            return
        try:
            self.db.add_topic(topic_name)
        except sqlite3.IntegrityError:
            show_error(self.window, "Validation Error", "Topic already exists.")
            return
        self.topic_entry.delete(0, tk.END)
        self.refresh_topics_levels()
        show_info(self.window, "Success", "Topic added.")

    def _add_level(self):
        level_name = self.level_entry.get().strip()
        if not level_name:
            show_error(self.window, "Validation Error", "Level name is required.")
            return
        try:
            self.db.add_level(level_name)
        except sqlite3.IntegrityError:
            show_error(self.window, "Validation Error", "Level already exists.")
            return
        self.level_entry.delete(0, tk.END)
        self.refresh_topics_levels()
        show_info(self.window, "Success", "Level added.")

    def _add_question(self):
        topic_raw = self.topic_combo.get().strip()
        level_raw = self.level_combo.get().strip()
        question_text = self.question_text.get("1.0", tk.END).strip()
        options = [entry.get().strip() for entry in self.option_entries]
        correct_option_raw = self.correct_option_combo.get()

        if not topic_raw or not level_raw:
            show_error(self.window, "Validation Error", "Select topic and level.")
            return
        if not question_text:
            show_error(self.window, "Validation Error", "Question text is required.")
            return
        if any(not option for option in options):
            show_error(self.window, "Validation Error", "All options are required.")
            return
        if len(set(option.lower() for option in options)) < len(options):
            show_error(self.window, "Validation Error", "Options must be unique.")
            return

        topic_id = int(topic_raw.split(":")[0])
        level_id = int(level_raw.split(":")[0])
        correct_index = int(correct_option_raw) - 1
        self.db.add_question(topic_id, level_id, question_text, options, correct_index)

        self.question_text.delete("1.0", tk.END)
        for entry in self.option_entries:
            entry.delete(0, tk.END)
        self.correct_option_combo.set("1")
        self.refresh_question_overview()
        show_info(self.window, "Success", "Question added.")

    def _extract_combo_id(self, raw_value: str):
        value = raw_value.strip()
        if not value:
            return None
        try:
            return int(value.split(":")[0])
        except ValueError:
            return None

    def _on_rule_selection_change(self, _event=None):
        self._load_test_rule_into_form()

    def _load_test_rule_into_form(self):
        topic_id = self._extract_combo_id(self.topic_combo.get())
        level_id = self._extract_combo_id(self.level_combo.get())
        if topic_id is None or level_id is None:
            return
        rule = self.db.get_test_rule(topic_id, level_id)
        duration_minutes = max(1, int(round(rule["duration_seconds"] / 60)))
        self.duration_entry.delete(0, tk.END)
        self.duration_entry.insert(0, str(duration_minutes))
        self.passing_percent_entry.delete(0, tk.END)
        self.passing_percent_entry.insert(0, f'{float(rule["passing_percent"]):.2f}')

    def _save_test_rule(self):
        topic_id = self._extract_combo_id(self.topic_combo.get())
        level_id = self._extract_combo_id(self.level_combo.get())
        if topic_id is None or level_id is None:
            show_error(self.window, "Validation Error", "Select topic and level first.")
            return

        duration_raw = self.duration_entry.get().strip()
        passing_raw = self.passing_percent_entry.get().strip()
        try:
            duration_minutes = int(duration_raw)
        except ValueError:
            show_error(self.window, "Validation Error", "Duration must be an integer in minutes.")
            return
        try:
            passing_percent = float(passing_raw)
        except ValueError:
            show_error(self.window, "Validation Error", "Passing percent must be a number.")
            return
        if duration_minutes < 1:
            show_error(self.window, "Validation Error", "Duration must be at least 1 minute.")
            return
        if passing_percent <= 0 or passing_percent > 100:
            show_error(self.window, "Validation Error", "Passing percent must be between 0 and 100.")
            return

        self.db.save_test_rule(
            topic_id=topic_id,
            level_id=level_id,
            duration_seconds=duration_minutes * 60,
            passing_percent=passing_percent,
        )
        show_info(self.window, "Success", "Test rules saved for selected topic and level.")


class TestSessionWindow:
    def __init__(
        self,
        parent: tk.Tk,
        db: DatabaseManager,
        user_name: str,
        topic_id: int,
        topic_name: str,
        level_id: int,
        level_name: str,
        duration_seconds: int,
        passing_percent: float,
        on_complete,
    ):
        self.parent = parent
        self.db = db
        self.user_name = user_name
        self.topic_id = topic_id
        self.topic_name = topic_name
        self.level_id = level_id
        self.level_name = level_name
        self.duration_seconds = duration_seconds
        self.passing_percent = passing_percent
        self.on_complete = on_complete

        self.started_at = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.violations = 0
        self.current_index = 0
        self.answers = []
        self.session_ended = False
        self.currently_out_of_focus = False
        self.focus_monitor_job = None
        self.timer_job = None
        self.anti_cheat_armed = False
        self.anti_cheat_arm_at = time.monotonic() + 1.5
        self.remaining_seconds = self.duration_seconds

        base_questions = self.db.get_questions(topic_id, level_id)
        if not base_questions:
            raise ValueError("No questions available for this topic and level.")
        self.questions = self._build_shuffled_session(base_questions)
        self.answers = [-1] * len(self.questions)

        self.window = tk.Toplevel(parent)
        self.window.title(f"Test Session - {topic_name} / {level_name}")
        self.window.geometry("1000x620")
        self.window.attributes("-topmost", True)
        self.window.protocol("WM_DELETE_WINDOW", self._block_manual_close)
        self.window.bind("<FocusOut>", self._on_focus_out)
        self.window.bind("<FocusIn>", self._on_focus_in)

        content = ttk.Frame(self.window, padding=16)
        content.pack(fill="both", expand=True)

        self.info_label = ttk.Label(
            content,
            text=f"Candidate: {user_name} | Topic: {topic_name} | Level: {level_name}",
        )
        self.info_label.pack(anchor="w")

        self.progress_label = ttk.Label(content, text="")
        self.progress_label.pack(anchor="w", pady=(6, 0))

        self.violation_label = ttk.Label(
            content,
            text=f"Anti-cheat violations: 0/{MAX_VIOLATIONS} allowed",
            foreground="darkred",
        )
        self.violation_label.pack(anchor="w", pady=(3, 10))

        self.timer_label = ttk.Label(content, text="", foreground="darkblue")
        self.timer_label.pack(anchor="w", pady=(0, 8))

        self.warning_label = ttk.Label(content, text="", foreground="red")
        self.warning_label.pack(anchor="w", pady=(0, 8))

        self.question_label = ttk.Label(content, text="", wraplength=930, justify="left")
        self.question_label.pack(anchor="w", pady=(10, 14))

        self.selected_option = tk.IntVar(value=-1)
        self.option_buttons = []
        for option_idx in range(4):
            button = ttk.Radiobutton(
                content,
                text="",
                variable=self.selected_option,
                value=option_idx,
            )
            button.pack(anchor="w", pady=4)
            self.option_buttons.append(button)

        self.nav_button = ttk.Button(content, text="Next", command=self._next_question)
        self.nav_button.pack(anchor="e", pady=(18, 0))

        self.window.grab_set()
        self.window.focus_force()
        self._render_question()
        self._update_timer_label()
        self._schedule_timer_tick()
        self._poll_focus_state()

    def _build_shuffled_session(self, base_questions: list[dict]):
        session_questions = []
        for question in base_questions:
            option_order = list(range(len(question["options"])))
            random.shuffle(option_order)
            shuffled_options = [question["options"][idx] for idx in option_order]
            shuffled_correct_index = option_order.index(question["correct_index"])
            session_questions.append(
                {
                    "question_text": question["question_text"],
                    "options": shuffled_options,
                    "correct_index": shuffled_correct_index,
                }
            )
        random.shuffle(session_questions)
        return session_questions

    def _render_question(self):
        current_question = self.questions[self.current_index]
        self.progress_label.config(
            text=f"Question {self.current_index + 1} of {len(self.questions)}"
        )
        self.question_label.config(text=current_question["question_text"])

        for idx, option_text in enumerate(current_question["options"]):
            self.option_buttons[idx].config(text=option_text)
        self.selected_option.set(self.answers[self.current_index])

        if self.current_index == len(self.questions) - 1:
            self.nav_button.config(text="Submit Test")
        else:
            self.nav_button.config(text="Next")

    def _next_question(self):
        selected = self.selected_option.get()
        if selected == -1:
            self.warning_label.config(
                text="Select an answer before continuing to the next question."
            )
            return

        self.warning_label.config(text="")
        self.answers[self.current_index] = selected
        if self.current_index < len(self.questions) - 1:
            self.current_index += 1
            self._render_question()
        else:
            self._finish_session(status="completed")

    def _on_focus_out(self, _event):
        if self.session_ended:
            return
        if not self.anti_cheat_armed:
            return
        # Defer check slightly to avoid false positives from internal widget focus changes.
        self.window.after(60, self._check_focus_transition)

    def _on_focus_in(self, _event):
        if self.session_ended:
            return
        if time.monotonic() >= self.anti_cheat_arm_at:
            self.anti_cheat_armed = True
        self.currently_out_of_focus = False

    def _check_focus_transition(self):
        if self.session_ended:
            return
        if not self._window_is_foreground():
            self._register_violation()

    def _poll_focus_state(self):
        if self.session_ended:
            return

        if not self.anti_cheat_armed and time.monotonic() >= self.anti_cheat_arm_at:
            # Arm anti-cheat only after startup settles to avoid first-load false positives.
            self.anti_cheat_armed = True
            self.currently_out_of_focus = False

        if not self.anti_cheat_armed:
            self.focus_monitor_job = self.window.after(350, self._poll_focus_state)
            return

        if self._window_is_foreground():
            self.currently_out_of_focus = False
        else:
            self._register_violation()
        self.focus_monitor_job = self.window.after(350, self._poll_focus_state)

    def _window_is_foreground(self):
        try:
            if sys.platform.startswith("win"):
                import ctypes

                user32 = ctypes.windll.user32
                test_hwnd = int(self.window.winfo_id())
                foreground_hwnd = int(user32.GetForegroundWindow())
                if foreground_hwnd == 0:
                    return False
                if foreground_hwnd == test_hwnd:
                    return True
                # Foreground might be a child control (button/radiobutton/text widget)
                # inside the test window, not always the toplevel hwnd itself.
                if bool(user32.IsChild(test_hwnd, foreground_hwnd)):
                    return True

                ga_root = 2
                foreground_root = int(user32.GetAncestor(foreground_hwnd, ga_root))
                test_root = int(user32.GetAncestor(test_hwnd, ga_root))
                return foreground_root != 0 and foreground_root == test_root
        except Exception:
            pass

        focused_widget = self.window.focus_displayof()
        if focused_widget is None:
            return False
        return focused_widget.winfo_toplevel() == self.window

    def _update_timer_label(self):
        minutes, seconds = divmod(max(0, self.remaining_seconds), 60)
        self.timer_label.config(
            text=(
                f"Time remaining: {minutes:02d}:{seconds:02d} "
                f"| Pass threshold: {self.passing_percent:.2f}%"
            )
        )

    def _schedule_timer_tick(self):
        if self.session_ended:
            return
        self._update_timer_label()
        if self.remaining_seconds <= 0:
            self.warning_label.config(text="Time is up. The test ended automatically.")
            self._finish_session(status="failed_timeout")
            return
        self.remaining_seconds -= 1
        self.timer_job = self.window.after(1000, self._schedule_timer_tick)

    def _register_violation(self):
        if self.currently_out_of_focus or self.session_ended:
            return

        self.currently_out_of_focus = True
        self.violations += 1
        self.violation_label.config(
            text=f"Anti-cheat violations: {self.violations}/{MAX_VIOLATIONS} allowed"
        )

        if self.violations > MAX_VIOLATIONS:
            self.warning_label.config(
                text="Violation limit exceeded. Test ended and marked as failed."
            )
            self._finish_session(status="failed_anticheat")
            return

        remaining = MAX_VIOLATIONS - self.violations
        self.warning_label.config(
            text=(
                f"Warning: you switched away from the test window. "
                f"Remaining allowed violations: {remaining}."
            )
        )

    def _calculate_score(self):
        score = 0
        for idx, question in enumerate(self.questions):
            if self.answers[idx] == question["correct_index"]:
                score += 1
        return score

    def _finish_session(self, status: str):
        if self.session_ended:
            return
        self.session_ended = True
        if self.focus_monitor_job is not None:
            self.window.after_cancel(self.focus_monitor_job)
            self.focus_monitor_job = None
        if self.timer_job is not None:
            self.window.after_cancel(self.timer_job)
            self.timer_job = None

        score = self._calculate_score()
        total_questions = len(self.questions)
        required_correct = int((total_questions * self.passing_percent / 100) + 0.999)
        passed = status == "completed" and score >= required_correct
        ended_at = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        if status in {"failed_anticheat", "failed_timeout"}:
            passed = False

        self.db.save_attempt(
            user_name=self.user_name,
            topic_name=self.topic_name,
            level_name=self.level_name,
            score=score,
            total_questions=total_questions,
            passed=passed,
            violations=self.violations,
            status=status,
            started_at=self.started_at,
            ended_at=ended_at,
        )

        if status == "failed_anticheat":
            show_error(
                self.window,
                "Test Ended",
                "You exceeded the allowed anti-cheat violations. You failed this test.",
            )
        elif status == "failed_timeout":
            show_error(
                self.window,
                "Time Expired",
                "Test time has expired. The attempt is marked as failed.",
            )
        else:
            passed_text = "PASSED" if passed else "FAILED"
            show_info(
                self.window,
                "Test Complete",
                f"Score: {score}/{total_questions}\nResult: {passed_text}\n"
                f"Violations: {self.violations}\n"
                f"Required pass threshold: {self.passing_percent:.2f}%",
            )

        self.window.destroy()
        self.on_complete()

    def _block_manual_close(self):
        show_warning(
            self.window,
            "Action Blocked",
            "Manual close is disabled while the test is active.",
        )


class TestingApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Desktop Testing Application")
        self.geometry("720x470")
        self.resizable(False, False)
        self.db = DatabaseManager(DB_PATH)

        self.main_frame = ttk.Frame(self, padding=24)
        self.main_frame.pack(fill="both", expand=True)

        self._show_home()

    def _clear_main(self):
        for widget in self.main_frame.winfo_children():
            widget.destroy()

    def _show_home(self):
        self._clear_main()

        ttk.Label(
            self.main_frame,
            text="Testing Application",
            font=("Segoe UI", 20, "bold"),
        ).pack(anchor="center", pady=(12, 8))

        ttk.Label(
            self.main_frame,
            text=(
                "Register as candidate to start a test.\n"
                "Admins can login to manage topics, levels, and questions."
            ),
            justify="center",
        ).pack(anchor="center", pady=(0, 18))

        ttk.Button(
            self.main_frame, text="Candidate Registration", command=self._show_registration
        ).pack(fill="x", pady=6)
        ttk.Button(
            self.main_frame, text="Admin Panel Login", command=self._open_admin_login
        ).pack(fill="x", pady=6)
        ttk.Button(self.main_frame, text="Exit", command=self.destroy).pack(fill="x", pady=6)

    def _open_admin_login(self):
        AdminLoginWindow(self, self.db)

    def _show_registration(self):
        self._clear_main()

        ttk.Label(
            self.main_frame, text="Candidate Registration", font=("Segoe UI", 16, "bold")
        ).pack(anchor="w", pady=(0, 12))

        form = ttk.Frame(self.main_frame)
        form.pack(fill="x")

        ttk.Label(form, text="Full name").grid(row=0, column=0, sticky="w")
        self.name_entry = ttk.Entry(form)
        self.name_entry.grid(row=0, column=1, sticky="ew", padx=(12, 0), pady=(0, 10))

        ttk.Label(form, text="Topic").grid(row=1, column=0, sticky="w")
        self.topic_selector = ttk.Combobox(form, state="readonly")
        self.topic_selector.grid(row=1, column=1, sticky="ew", padx=(12, 0), pady=(0, 10))
        self.topic_selector.bind("<<ComboboxSelected>>", self._refresh_level_selector)

        ttk.Label(form, text="Level").grid(row=2, column=0, sticky="w")
        self.level_selector = ttk.Combobox(form, state="readonly")
        self.level_selector.grid(row=2, column=1, sticky="ew", padx=(12, 0), pady=(0, 10))

        form.columnconfigure(1, weight=1)

        info_text = (
            f"Anti-cheat rule: if the test window loses focus more than {MAX_VIOLATIONS} times, "
            "the candidate fails automatically."
        )
        ttk.Label(self.main_frame, text=info_text, foreground="darkred", wraplength=650).pack(
            anchor="w", pady=(6, 12)
        )

        buttons = ttk.Frame(self.main_frame)
        buttons.pack(fill="x", pady=(6, 0))
        ttk.Button(buttons, text="Back", command=self._show_home).pack(side="left")
        ttk.Button(buttons, text="Start Test", command=self._start_test).pack(side="right")

        self._load_topics_for_registration()
        self.name_entry.focus_set()

    def _load_topics_for_registration(self):
        topics = self.db.get_topics()
        self._topic_map = {f'{topic["id"]}: {topic["name"]}': topic for topic in topics}
        topic_values = list(self._topic_map.keys())
        self.topic_selector["values"] = topic_values

        if topic_values:
            self.topic_selector.set(topic_values[0])
            self._refresh_level_selector()
        else:
            self.level_selector["values"] = []
            self.level_selector.set("")

    def _refresh_level_selector(self, _event=None):
        topic_raw = self.topic_selector.get().strip()
        if not topic_raw:
            self.level_selector["values"] = []
            self.level_selector.set("")
            return

        topic_id = int(topic_raw.split(":")[0])
        levels = self.db.get_levels_for_topic(topic_id)
        self._level_map = {f'{level["id"]}: {level["name"]}': level for level in levels}
        level_values = list(self._level_map.keys())
        self.level_selector["values"] = level_values
        if level_values:
            self.level_selector.set(level_values[0])
        else:
            self.level_selector.set("")

    def _start_test(self):
        user_name = self.name_entry.get().strip()
        topic_raw = self.topic_selector.get().strip()
        level_raw = self.level_selector.get().strip()

        if not user_name:
            show_error(self, "Validation Error", "Enter your name.")
            return
        if not topic_raw:
            show_error(
                self,
                "Validation Error",
                "No topics are available yet. Ask an admin to add content.",
            )
            return
        if not level_raw:
            show_error(
                self,
                "Validation Error",
                "No levels with questions are available for this topic yet.",
            )
            return

        topic_id = int(topic_raw.split(":")[0])
        topic_name = topic_raw.split(": ", 1)[1]
        level_id = int(level_raw.split(":")[0])
        level_name = level_raw.split(": ", 1)[1]
        test_rule = self.db.get_test_rule(topic_id, level_id)

        questions = self.db.get_questions(topic_id, level_id)
        if not questions:
            show_error(
                self,
                "Validation Error",
                "No questions available for selected topic/level.",
            )
            return

        self.withdraw()
        try:
            TestSessionWindow(
                parent=self,
                db=self.db,
                user_name=user_name,
                topic_id=topic_id,
                topic_name=topic_name,
                level_id=level_id,
                level_name=level_name,
                duration_seconds=test_rule["duration_seconds"],
                passing_percent=test_rule["passing_percent"],
                on_complete=self._on_test_complete,
            )
        except ValueError as error:
            self.deiconify()
            show_error(self, "Start Error", str(error))

    def _on_test_complete(self):
        self.deiconify()
        self._show_home()


if __name__ == "__main__":
    app = TestingApp()
    app.mainloop()
