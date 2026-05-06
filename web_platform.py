import os
from typing import Any
from urllib.parse import quote_plus

import requests
from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates


API_BASE_URL = os.getenv("PLATFORM_API_URL", "http://localhost:8000").rstrip("/")
COOKIE_NAME = "platform_token"

app = FastAPI(title="Testing Platform Web UI", version="1.0.0")
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")


def api_request(token: str | None, method: str, path: str, json: dict[str, Any] | None = None):
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    response = requests.request(
        method=method,
        url=f"{API_BASE_URL}{path}",
        headers=headers,
        json=json,
        timeout=25,
    )
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
    raise ValueError(detail)


def api_login(username: str, password: str):
    response = requests.post(
        f"{API_BASE_URL}/auth/login",
        data={"username": username, "password": password},
        timeout=25,
    )
    if response.ok:
        return response.json()
    detail = "Invalid credentials."
    try:
        detail = response.json().get("detail", detail)
    except Exception:
        pass
    raise ValueError(detail)


def get_token(request: Request) -> str | None:
    return request.cookies.get(COOKIE_NAME)


def redirect_to_login(message: str = ""):
    target = "/login"
    if message:
        target = f"/login?error={quote_plus(message)}"
    return RedirectResponse(target, status_code=303)


@app.get("/", response_class=HTMLResponse)
def root(request: Request):
    token = get_token(request)
    if token:
        return RedirectResponse("/dashboard", status_code=303)
    return RedirectResponse("/login", status_code=303)


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request, error: str = ""):
    return templates.TemplateResponse(
        request=request,
        name="login.html",
        context={
            "error": error,
            "api_base_url": API_BASE_URL,
        },
    )


@app.post("/login")
def login_submit(
    username: str = Form(...),
    password: str = Form(...),
):
    try:
        token_data = api_login(username.strip(), password)
    except ValueError as error:
        return RedirectResponse(f"/login?error={error}", status_code=303)

    response = RedirectResponse("/dashboard", status_code=303)
    response.set_cookie(
        key=COOKIE_NAME,
        value=token_data["access_token"],
        httponly=True,
        samesite="lax",
        max_age=60 * 60 * 12,
    )
    return response


@app.post("/logout")
def logout():
    response = RedirectResponse("/login", status_code=303)
    response.delete_cookie(COOKIE_NAME)
    return response


@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request, message: str = "", error: str = ""):
    token = get_token(request)
    if not token:
        return redirect_to_login("Please log in first.")

    try:
        me = api_request(token, "GET", "/auth/me")
        profile = api_request(token, "GET", "/profile/me")
        catalog = api_request(token, "GET", "/tests/catalog")
    except ValueError as api_error:
        return redirect_to_login(str(api_error))

    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context={
            "me": me,
            "profile": profile,
            "catalog": catalog,
            "message": message,
            "error": error,
            "is_admin": me["role"] in {"admin", "super_admin"},
        },
    )


@app.get("/tests/{test_config_id}", response_class=HTMLResponse)
def start_test(request: Request, test_config_id: int):
    token = get_token(request)
    if not token:
        return redirect_to_login("Please log in first.")
    try:
        me = api_request(token, "GET", "/auth/me")
        payload = api_request(token, "POST", f"/tests/start/{test_config_id}")
    except ValueError as api_error:
        return RedirectResponse(f"/dashboard?error={api_error}", status_code=303)

    return templates.TemplateResponse(
        request=request,
        name="test.html",
        context={
            "me": me,
            "attempt": payload,
            "test_config_id": test_config_id,
        },
    )


@app.post("/tests/{attempt_id}/submit")
async def submit_test(request: Request, attempt_id: int):
    token = get_token(request)
    if not token:
        return redirect_to_login("Please log in first.")

    form = await request.form()

    # Form keys are generated as answer_<question_id>
    answers: dict[int, int] = {}
    for key, value in form.items():
        if not key.startswith("answer_"):
            continue
        try:
            question_id = int(key.split("_", 1)[1])
            selected = int(value)
        except (ValueError, TypeError):
            continue
        answers[question_id] = selected

    try:
        result = api_request(token, "POST", f"/tests/submit/{attempt_id}", json={"answers": answers})
        message = (
            f"Test submitted. Result: {'PASSED' if result['passed'] else 'FAILED'} | "
            f"Score: {result['score']}/{result['total_questions']} | "
            f"Credits left: {result['remaining_credits']}"
        )
        return RedirectResponse(f"/dashboard?message={quote_plus(message)}", status_code=303)
    except ValueError as api_error:
        return RedirectResponse(f"/dashboard?error={quote_plus(str(api_error))}", status_code=303)


@app.get("/admin", response_class=HTMLResponse)
def admin_page(request: Request, message: str = "", error: str = ""):
    token = get_token(request)
    if not token:
        return redirect_to_login("Please log in first.")
    try:
        me = api_request(token, "GET", "/auth/me")
        if me["role"] not in {"admin", "super_admin"}:
            return RedirectResponse("/dashboard?error=Admin+access+required.", status_code=303)
        users = api_request(token, "GET", "/admin/users")
        test_configs = api_request(token, "GET", "/admin/test-configs")
    except ValueError as api_error:
        return RedirectResponse(f"/dashboard?error={quote_plus(str(api_error))}", status_code=303)

    return templates.TemplateResponse(
        request=request,
        name="admin.html",
        context={
            "me": me,
            "users": users,
            "test_configs": test_configs,
            "message": message,
            "error": error,
            "can_add_admin": me["role"] == "super_admin",
        },
    )


@app.post("/admin/users")
def admin_create_user(
    request: Request,
    username: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    role: str = Form("user"),
    credits: int = Form(0),
):
    token = get_token(request)
    if not token:
        return redirect_to_login("Please log in first.")
    try:
        api_request(
            token,
            "POST",
            "/admin/users",
            json={
                "username": username.strip(),
                "email": email.strip(),
                "password": password,
                "role": role,
                "credits": credits,
            },
        )
        return RedirectResponse("/admin?message=User+created+successfully.", status_code=303)
    except ValueError as api_error:
        return RedirectResponse(f"/admin?error={quote_plus(str(api_error))}", status_code=303)


@app.post("/admin/credits")
def admin_add_credits(request: Request, user_id: int = Form(...), credits_to_add: int = Form(...)):
    token = get_token(request)
    if not token:
        return redirect_to_login("Please log in first.")
    try:
        api_request(token, "PATCH", f"/admin/users/{user_id}/credits", json={"credits_to_add": credits_to_add})
        return RedirectResponse("/admin?message=Credits+added.", status_code=303)
    except ValueError as api_error:
        return RedirectResponse(f"/admin?error={quote_plus(str(api_error))}", status_code=303)


@app.post("/admin/test-configs")
def admin_upsert_test_config(
    request: Request,
    topic_name: str = Form(...),
    level_name: str = Form(...),
    duration_minutes: int = Form(...),
    passing_percent: float = Form(...),
):
    token = get_token(request)
    if not token:
        return redirect_to_login("Please log in first.")
    try:
        api_request(
            token,
            "POST",
            "/admin/test-configs",
            json={
                "topic_name": topic_name.strip(),
                "level_name": level_name.strip(),
                "duration_seconds": max(1, duration_minutes) * 60,
                "passing_percent": passing_percent,
                "is_active": True,
            },
        )
        return RedirectResponse("/admin?message=Test+config+saved.", status_code=303)
    except ValueError as api_error:
        return RedirectResponse(f"/admin?error={quote_plus(str(api_error))}", status_code=303)


@app.post("/admin/questions")
def admin_add_question(
    request: Request,
    test_config_id: int = Form(...),
    question_text: str = Form(...),
    option_1: str = Form(...),
    option_2: str = Form(...),
    option_3: str = Form(...),
    option_4: str = Form(...),
    correct_index: int = Form(...),
):
    token = get_token(request)
    if not token:
        return redirect_to_login("Please log in first.")
    options = [option_1.strip(), option_2.strip(), option_3.strip(), option_4.strip()]
    try:
        api_request(
            token,
            "POST",
            "/admin/questions",
            json={
                "test_config_id": test_config_id,
                "question_text": question_text.strip(),
                "options": options,
                "correct_index": correct_index,
            },
        )
        return RedirectResponse("/admin?message=Question+added.", status_code=303)
    except ValueError as api_error:
        return RedirectResponse(f"/admin?error={quote_plus(str(api_error))}", status_code=303)
