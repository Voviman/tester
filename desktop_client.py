import os
import tkinter as tk
from tkinter import messagebox, ttk

import requests


API_BASE_URL = os.getenv("PLATFORM_API_URL", "http://localhost:8000").rstrip("/")


class APIError(Exception):
    pass


class PlatformAPIClient:
    def __init__(self, base_url: str):
        self.base_url = base_url
        self.token: str | None = None

    def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict | None = None,
        data: dict | None = None,
        auth: bool = True,
    ):
        headers = {}
        if auth:
            if not self.token:
                raise APIError("Not authenticated.")
            headers["Authorization"] = f"Bearer {self.token}"
        try:
            response = requests.request(
                method=method,
                url=f"{self.base_url}{path}",
                headers=headers,
                json=json,
                data=data,
                timeout=25,
            )
        except requests.RequestException as error:
            raise APIError(f"Network error: {error}") from error

        if response.ok:
            if response.text:
                return response.json()
            return {}

        detail = f"{response.status_code} error"
        try:
            detail = response.json().get("detail", detail)
        except Exception:
            if response.text:
                detail = response.text
        raise APIError(detail)

    def login(self, username_or_email: str, password: str):
        payload = self._request(
            "POST",
            "/auth/login",
            data={"username": username_or_email, "password": password},
            auth=False,
        )
        self.token = payload["access_token"]
        return self.me()

    def me(self):
        return self._request("GET", "/auth/me")

    def profile_me(self):
        return self._request("GET", "/profile/me")

    def tests_catalog(self):
        return self._request("GET", "/tests/catalog")

    def start_test(self, test_config_id: int):
        return self._request("POST", f"/tests/start/{test_config_id}")

    def submit_test(self, attempt_id: int, answers: dict[int, int]):
        return self._request("POST", f"/tests/submit/{attempt_id}", json={"answers": answers})

    def admin_users(self):
        return self._request("GET", "/admin/users")

    def admin_create_user(self, username: str, email: str, password: str, role: str, credits: int):
        return self._request(
            "POST",
            "/admin/users",
            json={
                "username": username,
                "email": email,
                "password": password,
                "role": role,
                "credits": credits,
            },
        )

    def admin_add_credits(self, user_id: int, credits_to_add: int):
        return self._request(
            "PATCH",
            f"/admin/users/{user_id}/credits",
            json={"credits_to_add": credits_to_add},
        )

    def admin_test_configs(self):
        return self._request("GET", "/admin/test-configs")

    def admin_upsert_test_config(
        self,
        topic_name: str,
        level_name: str,
        duration_minutes: int,
        passing_percent: float,
    ):
        return self._request(
            "POST",
            "/admin/test-configs",
            json={
                "topic_name": topic_name,
                "level_name": level_name,
                "duration_seconds": duration_minutes * 60,
                "passing_percent": passing_percent,
                "is_active": True,
            },
        )

    def admin_add_question(
        self,
        test_config_id: int,
        question_text: str,
        options: list[str],
        correct_index: int,
    ):
        return self._request(
            "POST",
            "/admin/questions",
            json={
                "test_config_id": test_config_id,
                "question_text": question_text,
                "options": options,
                "correct_index": correct_index,
            },
        )


class TestWindow:
    def __init__(self, parent, api: PlatformAPIClient, start_payload: dict, on_complete):
        self.parent = parent
        self.api = api
        self.on_complete = on_complete
        self.attempt_id = start_payload["attempt_id"]
        self.questions = start_payload["questions"]
        self.remaining_seconds = int(start_payload["duration_seconds"])
        self.passing_percent = float(start_payload["passing_percent"])
        self.current_index = 0
        self.answers: dict[int, int] = {}
        self.timer_job = None
        self.submitted = False

        self.window = tk.Toplevel(parent)
        self.window.title("Test Session")
        self.window.geometry("900x640")
        self.window.protocol("WM_DELETE_WINDOW", self._on_close_attempt)

        main = ttk.Frame(self.window, padding=16)
        main.pack(fill="both", expand=True)

        self.meta_label = ttk.Label(main, text="")
        self.meta_label.pack(anchor="w")

        self.timer_label = ttk.Label(main, text="", foreground="darkblue")
        self.timer_label.pack(anchor="w", pady=(4, 12))

        self.question_label = ttk.Label(main, text="", wraplength=840, justify="left")
        self.question_label.pack(anchor="w", pady=(6, 8))

        self.selected_option = tk.IntVar(value=-1)
        self.option_buttons = []
        for idx in range(4):
            button = ttk.Radiobutton(main, text="", variable=self.selected_option, value=idx)
            button.pack(anchor="w", pady=4)
            self.option_buttons.append(button)

        self.warning_label = ttk.Label(main, text="", foreground="darkred")
        self.warning_label.pack(anchor="w", pady=(8, 0))

        nav = ttk.Frame(main)
        nav.pack(fill="x", pady=(16, 0))

        self.prev_button = ttk.Button(nav, text="Previous", command=self._previous)
        self.prev_button.pack(side="left")

        self.next_button = ttk.Button(nav, text="Next", command=self._next)
        self.next_button.pack(side="right")

        self.submit_button = ttk.Button(nav, text="Submit Test", command=self._submit)
        self.submit_button.pack(side="right", padx=(0, 8))

        self._render_question()
        self._tick()

    def _on_close_attempt(self):
        messagebox.showwarning(
            "Action blocked",
            "Please submit the test using the Submit Test button.",
            parent=self.window,
        )

    def _question(self):
        return self.questions[self.current_index]

    def _render_question(self):
        question = self._question()
        question_id = int(question["id"])
        self.meta_label.config(
            text=f"Question {self.current_index + 1}/{len(self.questions)} | Pass threshold: {self.passing_percent:.2f}%"
        )
        self.question_label.config(text=question["question_text"])
        for idx, option_text in enumerate(question["options"]):
            self.option_buttons[idx].config(text=option_text)
        self.selected_option.set(self.answers.get(question_id, -1))
        self.prev_button.config(state="normal" if self.current_index > 0 else "disabled")
        self.next_button.config(state="normal" if self.current_index < len(self.questions) - 1 else "disabled")

    def _save_current_answer(self):
        selected = self.selected_option.get()
        question_id = int(self._question()["id"])
        if selected >= 0:
            self.answers[question_id] = selected
            self.warning_label.config(text="")
        else:
            self.warning_label.config(text="No option selected for current question.")

    def _previous(self):
        self._save_current_answer()
        if self.current_index > 0:
            self.current_index -= 1
            self._render_question()

    def _next(self):
        self._save_current_answer()
        if self.current_index < len(self.questions) - 1:
            self.current_index += 1
            self._render_question()

    def _tick(self):
        if self.submitted:
            return
        minutes, seconds = divmod(max(self.remaining_seconds, 0), 60)
        self.timer_label.config(text=f"Time remaining: {minutes:02d}:{seconds:02d}")
        if self.remaining_seconds <= 0:
            self._submit(forced=True)
            return
        self.remaining_seconds -= 1
        self.timer_job = self.window.after(1000, self._tick)

    def _submit(self, forced: bool = False):
        if self.submitted:
            return
        self._save_current_answer()

        if not forced:
            confirmed = messagebox.askyesno(
                "Submit Test",
                "Are you sure you want to submit this test?",
                parent=self.window,
            )
            if not confirmed:
                return

        self.submitted = True
        if self.timer_job is not None:
            self.window.after_cancel(self.timer_job)

        try:
            result = self.api.submit_test(self.attempt_id, self.answers)
        except APIError as error:
            self.submitted = False
            self._tick()
            messagebox.showerror("Submit error", str(error), parent=self.window)
            return

        status = "PASSED" if result["passed"] else "FAILED"
        messagebox.showinfo(
            "Test complete",
            (
                f"Result: {status}\n"
                f"Score: {result['score']}/{result['total_questions']}\n"
                f"Success: {result['success_percent']:.2f}%\n"
                f"Remaining credits: {result['remaining_credits']}"
            ),
            parent=self.window,
        )
        self.window.destroy()
        self.on_complete()


class DesktopPlatformApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Testing Platform Desktop")
        self.geometry("1120x760")
        self.minsize(980, 680)
        self.api = PlatformAPIClient(API_BASE_URL)
        self.user = None
        self._catalog_rows = []

        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("Title.TLabel", font=("Segoe UI", 22, "bold"))
        style.configure("Subtitle.TLabel", font=("Segoe UI", 10))

        self.container = ttk.Frame(self, padding=18)
        self.container.pack(fill="both", expand=True)

        self._show_login_view()

    def _clear(self):
        for widget in self.container.winfo_children():
            widget.destroy()

    def _show_login_view(self):
        self._clear()
        card = ttk.Frame(self.container, padding=20)
        card.place(relx=0.5, rely=0.45, anchor="center")

        ttk.Label(card, text="Testing Platform", style="Title.TLabel").pack(anchor="center")
        ttk.Label(
            card,
            text=f"Shared credentials for website and desktop\nAPI: {API_BASE_URL}",
            style="Subtitle.TLabel",
        ).pack(anchor="center", pady=(2, 16))

        ttk.Label(card, text="Username or Email").pack(anchor="w")
        self.login_user_entry = ttk.Entry(card, width=42)
        self.login_user_entry.pack(fill="x", pady=(2, 10))

        ttk.Label(card, text="Password").pack(anchor="w")
        self.login_pass_entry = ttk.Entry(card, width=42, show="*")
        self.login_pass_entry.pack(fill="x", pady=(2, 14))
        self.login_pass_entry.bind("<Return>", self._login_submit)

        ttk.Button(card, text="Login", command=self._login_submit).pack(fill="x")
        self.login_user_entry.focus_set()

    def _login_submit(self, _event=None):
        username = self.login_user_entry.get().strip()
        password = self.login_pass_entry.get()
        if not username or not password:
            messagebox.showerror("Validation", "Enter both username/email and password.", parent=self)
            return
        try:
            self.user = self.api.login(username, password)
        except APIError as error:
            messagebox.showerror("Login failed", str(error), parent=self)
            return
        self._show_main_view()

    def _show_main_view(self):
        self._clear()

        top = ttk.Frame(self.container)
        top.pack(fill="x")
        self.user_header_var = tk.StringVar()
        ttk.Label(top, textvariable=self.user_header_var, style="Subtitle.TLabel").pack(side="left")
        ttk.Button(top, text="Refresh", command=self._refresh_all).pack(side="right")
        ttk.Button(top, text="Logout", command=self._logout).pack(side="right", padx=(0, 8))

        self.notebook = ttk.Notebook(self.container)
        self.notebook.pack(fill="both", expand=True, pady=(12, 0))

        self.dashboard_tab = ttk.Frame(self.notebook, padding=12)
        self.tests_tab = ttk.Frame(self.notebook, padding=12)
        self.notebook.add(self.dashboard_tab, text="Dashboard")
        self.notebook.add(self.tests_tab, text="Take Test")

        if self.user["role"] in {"admin", "super_admin"}:
            self.admin_tab = ttk.Frame(self.notebook, padding=12)
            self.notebook.add(self.admin_tab, text="Admin")
            self._build_admin_tab()
        else:
            self.admin_tab = None

        self._build_dashboard_tab()
        self._build_tests_tab()
        self._refresh_all()

    def _logout(self):
        self.user = None
        self.api.token = None
        self._show_login_view()

    def _build_dashboard_tab(self):
        self.profile_box = tk.Text(self.dashboard_tab, height=16, wrap="word")
        self.profile_box.pack(fill="both", expand=True)
        self.profile_box.configure(state="disabled")

    def _build_tests_tab(self):
        columns = ("id", "topic", "level", "duration", "pass", "questions")
        self.catalog_tree = ttk.Treeview(self.tests_tab, columns=columns, show="headings", height=14)
        for col, title, width in [
            ("id", "ID", 60),
            ("topic", "Topic", 220),
            ("level", "Level", 180),
            ("duration", "Duration", 130),
            ("pass", "Pass %", 110),
            ("questions", "Questions", 110),
        ]:
            self.catalog_tree.heading(col, text=title)
            self.catalog_tree.column(col, width=width, anchor="center")
        self.catalog_tree.column("topic", anchor="w")
        self.catalog_tree.column("level", anchor="w")
        self.catalog_tree.pack(fill="both", expand=True)

        actions = ttk.Frame(self.tests_tab)
        actions.pack(fill="x", pady=(10, 0))
        ttk.Button(actions, text="Refresh Catalog", command=self._refresh_catalog).pack(side="left")
        ttk.Button(actions, text="Start Selected Test", command=self._start_selected_test).pack(side="right")

    def _build_admin_tab(self):
        root = ttk.Frame(self.admin_tab)
        root.pack(fill="both", expand=True)
        root.columnconfigure(0, weight=1)
        root.columnconfigure(1, weight=1)

        forms = ttk.Frame(root)
        forms.grid(row=0, column=0, sticky="nsew", padx=(0, 8))

        tables = ttk.Frame(root)
        tables.grid(row=0, column=1, sticky="nsew", padx=(8, 0))

        create_frame = ttk.LabelFrame(forms, text="Create User", padding=10)
        create_frame.pack(fill="x", pady=(0, 10))
        self.new_user_username = ttk.Entry(create_frame)
        self.new_user_email = ttk.Entry(create_frame)
        self.new_user_password = ttk.Entry(create_frame, show="*")
        role_values = ["user"] if self.user["role"] == "admin" else ["user", "admin"]
        self.new_user_role = ttk.Combobox(create_frame, state="readonly", values=role_values)
        self.new_user_role.set(role_values[0])
        self.new_user_credits = ttk.Entry(create_frame)
        self.new_user_credits.insert(0, "0")
        self._pack_labeled(create_frame, "Username", self.new_user_username)
        self._pack_labeled(create_frame, "Email", self.new_user_email)
        self._pack_labeled(create_frame, "Password", self.new_user_password)
        self._pack_labeled(create_frame, "Role", self.new_user_role)
        self._pack_labeled(create_frame, "Credits", self.new_user_credits)
        ttk.Button(create_frame, text="Create User", command=self._admin_create_user).pack(fill="x", pady=(8, 0))

        credit_frame = ttk.LabelFrame(forms, text="Add Credits", padding=10)
        credit_frame.pack(fill="x", pady=(0, 10))
        self.credit_user_id = ttk.Entry(credit_frame)
        self.credit_amount = ttk.Entry(credit_frame)
        self.credit_amount.insert(0, "1")
        self._pack_labeled(credit_frame, "User ID", self.credit_user_id)
        self._pack_labeled(credit_frame, "Credits to add", self.credit_amount)
        ttk.Button(credit_frame, text="Add Credits", command=self._admin_add_credits).pack(fill="x", pady=(8, 0))

        config_frame = ttk.LabelFrame(forms, text="Test Config", padding=10)
        config_frame.pack(fill="x", pady=(0, 10))
        self.config_topic = ttk.Entry(config_frame)
        self.config_level = ttk.Entry(config_frame)
        self.config_duration = ttk.Entry(config_frame)
        self.config_duration.insert(0, "15")
        self.config_pass = ttk.Entry(config_frame)
        self.config_pass.insert(0, "60")
        self._pack_labeled(config_frame, "Topic", self.config_topic)
        self._pack_labeled(config_frame, "Level", self.config_level)
        self._pack_labeled(config_frame, "Duration (minutes)", self.config_duration)
        self._pack_labeled(config_frame, "Passing %", self.config_pass)
        ttk.Button(config_frame, text="Save Config", command=self._admin_save_config).pack(fill="x", pady=(8, 0))

        question_frame = ttk.LabelFrame(forms, text="Add Question", padding=10)
        question_frame.pack(fill="both", expand=True)
        self.question_config_id = ttk.Entry(question_frame)
        self.question_text = tk.Text(question_frame, height=4)
        self.question_opts = [ttk.Entry(question_frame) for _ in range(4)]
        self.question_correct = ttk.Combobox(
            question_frame,
            state="readonly",
            values=["0", "1", "2", "3"],
            width=10,
        )
        self.question_correct.set("0")
        self._pack_labeled(question_frame, "Test Config ID", self.question_config_id)
        ttk.Label(question_frame, text="Question Text").pack(anchor="w")
        self.question_text.pack(fill="x", pady=(2, 8))
        for idx, entry in enumerate(self.question_opts, start=1):
            self._pack_labeled(question_frame, f"Option {idx}", entry)
        self._pack_labeled(question_frame, "Correct option index", self.question_correct)
        ttk.Button(question_frame, text="Add Question", command=self._admin_add_question).pack(
            fill="x",
            pady=(8, 0),
        )

        self.users_tree = ttk.Treeview(
            tables,
            columns=("id", "username", "email", "role", "credits"),
            show="headings",
            height=10,
        )
        for col, title, width in [
            ("id", "ID", 55),
            ("username", "Username", 140),
            ("email", "Email", 210),
            ("role", "Role", 110),
            ("credits", "Credits", 85),
        ]:
            self.users_tree.heading(col, text=title)
            self.users_tree.column(col, width=width, anchor="center")
        self.users_tree.column("username", anchor="w")
        self.users_tree.column("email", anchor="w")
        self.users_tree.pack(fill="x")

        self.config_tree = ttk.Treeview(
            tables,
            columns=("id", "topic", "level", "duration", "pass", "q"),
            show="headings",
            height=12,
        )
        for col, title, width in [
            ("id", "ID", 55),
            ("topic", "Topic", 145),
            ("level", "Level", 120),
            ("duration", "Min", 70),
            ("pass", "Pass %", 70),
            ("q", "Q", 50),
        ]:
            self.config_tree.heading(col, text=title)
            self.config_tree.column(col, width=width, anchor="center")
        self.config_tree.column("topic", anchor="w")
        self.config_tree.column("level", anchor="w")
        self.config_tree.pack(fill="both", expand=True, pady=(10, 0))

        ttk.Button(tables, text="Refresh Admin Data", command=self._refresh_admin).pack(anchor="e", pady=(8, 0))

    def _pack_labeled(self, parent, label: str, widget):
        ttk.Label(parent, text=label).pack(anchor="w")
        widget.pack(fill="x", pady=(2, 8))

    def _refresh_all(self):
        self._refresh_profile()
        self._refresh_catalog()
        if self.admin_tab is not None:
            self._refresh_admin()

    def _refresh_profile(self):
        try:
            self.user = self.api.me()
            profile = self.api.profile_me()
        except APIError as error:
            messagebox.showerror("Refresh error", str(error), parent=self)
            return

        self.user_header_var.set(
            f"Signed in as {self.user['username']} ({self.user['role']}) | Credits: {profile['user']['credits']}"
        )
        text = (
            "Profile Statistics\n"
            "==================\n"
            f"Username: {profile['user']['username']}\n"
            f"Email: {profile['user']['email']}\n"
            f"Role: {profile['user']['role']}\n"
            f"Credits: {profile['user']['credits']}\n\n"
            f"Tests done: {profile['tests_done']}\n"
            f"Passed tests: {profile['passed_tests']}\n"
            f"Failed tests: {profile['failed_tests']}\n"
            f"Success rate: {profile['success_rate_percent']:.2f}%\n"
        )
        self.profile_box.configure(state="normal")
        self.profile_box.delete("1.0", tk.END)
        self.profile_box.insert("1.0", text)
        self.profile_box.configure(state="disabled")

    def _refresh_catalog(self):
        try:
            self._catalog_rows = self.api.tests_catalog()
        except APIError as error:
            messagebox.showerror("Catalog error", str(error), parent=self)
            return
        for item in self.catalog_tree.get_children():
            self.catalog_tree.delete(item)
        for row in self._catalog_rows:
            self.catalog_tree.insert(
                "",
                "end",
                values=(
                    row["id"],
                    row["topic_name"],
                    row["level_name"],
                    f"{int(row['duration_seconds']) // 60} min",
                    f"{float(row['passing_percent']):.2f}",
                    row["question_count"],
                ),
            )

    def _start_selected_test(self):
        selected = self.catalog_tree.focus()
        if not selected:
            messagebox.showwarning("Selection required", "Select a test from catalog.", parent=self)
            return
        values = self.catalog_tree.item(selected, "values")
        test_config_id = int(values[0])
        try:
            payload = self.api.start_test(test_config_id)
        except APIError as error:
            messagebox.showerror("Start test error", str(error), parent=self)
            return
        TestWindow(self, self.api, payload, on_complete=self._refresh_all)

    def _refresh_admin(self):
        if self.admin_tab is None:
            return
        try:
            users = self.api.admin_users()
            configs = self.api.admin_test_configs()
        except APIError as error:
            messagebox.showerror("Admin error", str(error), parent=self)
            return

        for item in self.users_tree.get_children():
            self.users_tree.delete(item)
        for user in users:
            self.users_tree.insert(
                "",
                "end",
                values=(user["id"], user["username"], user["email"], user["role"], user["credits"]),
            )

        for item in self.config_tree.get_children():
            self.config_tree.delete(item)
        for config in configs:
            self.config_tree.insert(
                "",
                "end",
                values=(
                    config["id"],
                    config["topic_name"],
                    config["level_name"],
                    int(config["duration_seconds"]) // 60,
                    f"{float(config['passing_percent']):.2f}",
                    config["question_count"],
                ),
            )

    def _admin_create_user(self):
        username = self.new_user_username.get().strip()
        email = self.new_user_email.get().strip()
        password = self.new_user_password.get()
        role = self.new_user_role.get().strip()
        credits_raw = self.new_user_credits.get().strip()
        if not username or not email or not password or not role:
            messagebox.showerror("Validation", "Fill all user fields.", parent=self)
            return
        try:
            credits = int(credits_raw or "0")
            if credits < 0:
                raise ValueError
        except ValueError:
            messagebox.showerror("Validation", "Credits must be zero or positive integer.", parent=self)
            return
        try:
            self.api.admin_create_user(username, email, password, role, credits)
        except APIError as error:
            messagebox.showerror("Create user error", str(error), parent=self)
            return
        self.new_user_username.delete(0, tk.END)
        self.new_user_email.delete(0, tk.END)
        self.new_user_password.delete(0, tk.END)
        self.new_user_credits.delete(0, tk.END)
        self.new_user_credits.insert(0, "0")
        self._refresh_admin()
        messagebox.showinfo("Success", "User created.", parent=self)

    def _admin_add_credits(self):
        user_id_raw = self.credit_user_id.get().strip()
        amount_raw = self.credit_amount.get().strip()
        try:
            user_id = int(user_id_raw)
            amount = int(amount_raw)
            if amount <= 0:
                raise ValueError
        except ValueError:
            messagebox.showerror("Validation", "User ID and credits must be valid positive integers.", parent=self)
            return
        try:
            self.api.admin_add_credits(user_id, amount)
        except APIError as error:
            messagebox.showerror("Credits error", str(error), parent=self)
            return
        self._refresh_admin()
        self._refresh_profile()
        messagebox.showinfo("Success", "Credits added.", parent=self)

    def _admin_save_config(self):
        topic = self.config_topic.get().strip()
        level = self.config_level.get().strip()
        duration_raw = self.config_duration.get().strip()
        pass_raw = self.config_pass.get().strip()
        if not topic or not level:
            messagebox.showerror("Validation", "Topic and level are required.", parent=self)
            return
        try:
            duration = int(duration_raw)
            passing = float(pass_raw)
            if duration < 1 or passing <= 0 or passing > 100:
                raise ValueError
        except ValueError:
            messagebox.showerror("Validation", "Duration must be >=1 and pass% between 0 and 100.", parent=self)
            return
        try:
            self.api.admin_upsert_test_config(topic, level, duration, passing)
        except APIError as error:
            messagebox.showerror("Config error", str(error), parent=self)
            return
        self._refresh_admin()
        self._refresh_catalog()
        messagebox.showinfo("Success", "Test config saved.", parent=self)

    def _admin_add_question(self):
        config_id_raw = self.question_config_id.get().strip()
        question_text = self.question_text.get("1.0", tk.END).strip()
        options = [entry.get().strip() for entry in self.question_opts]
        correct_raw = self.question_correct.get().strip()
        try:
            config_id = int(config_id_raw)
            correct_index = int(correct_raw)
            if correct_index < 0 or correct_index > 3:
                raise ValueError
        except ValueError:
            messagebox.showerror("Validation", "Config ID and correct index are invalid.", parent=self)
            return
        if not question_text or any(not option for option in options):
            messagebox.showerror("Validation", "Question text and all options are required.", parent=self)
            return
        try:
            self.api.admin_add_question(config_id, question_text, options, correct_index)
        except APIError as error:
            messagebox.showerror("Question error", str(error), parent=self)
            return
        self.question_text.delete("1.0", tk.END)
        for entry in self.question_opts:
            entry.delete(0, tk.END)
        self.question_correct.set("0")
        self._refresh_admin()
        self._refresh_catalog()
        messagebox.showinfo("Success", "Question added.", parent=self)


if __name__ == "__main__":
    app = DesktopPlatformApp()
    app.mainloop()
