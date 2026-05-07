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
        return RedirectResponse(f"/login?error={quote_plus(str(error))}", status_code=303)

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
    except ValueError as api_error:
        return redirect_to_login(str(api_error))

    # Keep users logged in even if backend is temporarily outdated or mid-deploy.
    social_dashboard_data = {"tests": [], "active_users": [], "recent_results": [], "following_user_ids": []}
    comments = []
    try:
        social_dashboard_data = api_request(token, "GET", "/social/dashboard")
        comments = api_request(token, "GET", "/social/comments")
    except ValueError as api_error:
        error = (
            error
            or f"Community data is temporarily unavailable ({api_error}). "
            "Please redeploy backend API with latest version."
        )

    comments_by_test: dict[int, list[dict[str, Any]]] = {}
    for item in comments:
        test_id = int(item["test_config_id"])
        comments_by_test.setdefault(test_id, []).append(item)

    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context={
            "me": me,
            "profile": profile,
            "social_dashboard": social_dashboard_data,
            "comments_by_test": comments_by_test,
            "message": message,
            "error": error,
            "is_admin": me["role"] in {"admin", "super_admin"},
            "active_page": "dashboard",
        },
    )


@app.get("/profile", response_class=HTMLResponse)
def profile_page(request: Request, message: str = "", error: str = ""):
    token = get_token(request)
    if not token:
        return redirect_to_login("Please log in first.")

    try:
        me = api_request(token, "GET", "/auth/me")
        profile = api_request(token, "GET", "/profile/me")
    except ValueError as api_error:
        return redirect_to_login(str(api_error))

    social_dashboard_data = {"tests": [], "active_users": [], "recent_results": [], "following_user_ids": []}
    try:
        social_dashboard_data = api_request(token, "GET", "/social/dashboard")
    except ValueError as api_error:
        error = (
            error
            or f"Recent activity is temporarily unavailable ({api_error}). "
            "Please redeploy backend API with latest version."
        )

    my_results = [
        item for item in social_dashboard_data.get("recent_results", []) if int(item.get("user_id", 0)) == int(me["id"])
    ]

    return templates.TemplateResponse(
        request=request,
        name="profile.html",
        context={
            "me": me,
            "profile": profile,
            "my_results": my_results,
            "message": message,
            "error": error,
            "active_page": "profile",
        },
    )


@app.get("/tests/{test_config_id}", response_class=HTMLResponse)
def start_test(request: Request, test_config_id: int):
    return RedirectResponse(
        "/dashboard?error=Web+testing+is+disabled.+Please+use+desktop+application.",
        status_code=303,
    )


@app.post("/tests/{attempt_id}/submit")
async def submit_test(request: Request, attempt_id: int):
    return RedirectResponse(
        "/dashboard?error=Web+testing+is+disabled.+Please+use+desktop+application.",
        status_code=303,
    )


@app.post("/community/tests/{test_config_id}/comments")
def community_add_comment(
    request: Request,
    test_config_id: int,
    content: str = Form(...),
):
    token = get_token(request)
    if not token:
        return redirect_to_login("Please log in first.")
    try:
        api_request(
            token,
            "POST",
            f"/social/tests/{test_config_id}/comments",
            json={"content": content.strip()},
        )
        return RedirectResponse("/dashboard?message=Comment+posted.", status_code=303)
    except ValueError as api_error:
        return RedirectResponse(f"/dashboard?error={quote_plus(str(api_error))}", status_code=303)


@app.post("/community/follow/{target_user_id}")
def community_follow_user(request: Request, target_user_id: int):
    token = get_token(request)
    if not token:
        return redirect_to_login("Please log in first.")
    try:
        api_request(token, "POST", f"/social/follow/{target_user_id}")
        return RedirectResponse("/dashboard?message=You+are+now+following+this+user.", status_code=303)
    except ValueError as api_error:
        return RedirectResponse(f"/dashboard?error={quote_plus(str(api_error))}", status_code=303)


@app.post("/community/unfollow/{target_user_id}")
def community_unfollow_user(request: Request, target_user_id: int):
    token = get_token(request)
    if not token:
        return redirect_to_login("Please log in first.")
    try:
        api_request(token, "DELETE", f"/social/follow/{target_user_id}")
        return RedirectResponse("/dashboard?message=User+unfollowed.", status_code=303)
    except ValueError as api_error:
        return RedirectResponse(f"/dashboard?error={quote_plus(str(api_error))}", status_code=303)


@app.get("/admin", response_class=HTMLResponse)
def admin_page(
    request: Request,
    message: str = "",
    error: str = "",
    edit_question_id: int | None = None,
    question_config_id: str | None = None,
):
    token = get_token(request)
    if not token:
        return redirect_to_login("Please log in first.")
    try:
        me = api_request(token, "GET", "/auth/me")
        if me["role"] not in {"admin", "super_admin"}:
            return RedirectResponse("/dashboard?error=Admin+access+required.", status_code=303)
        users = api_request(token, "GET", "/admin/users")
        test_configs = api_request(token, "GET", "/admin/test-configs")
        question_filter_id = None
        if question_config_id and question_config_id.strip():
            question_filter_id = int(question_config_id.strip())
        question_path = "/admin/questions"
        if question_filter_id is not None:
            question_path = f"/admin/questions?test_config_id={question_filter_id}"
        questions = api_request(token, "GET", question_path)
    except ValueError as api_error:
        return RedirectResponse(f"/dashboard?error={quote_plus(str(api_error))}", status_code=303)
    except Exception:
        return RedirectResponse("/admin?error=Invalid+question+config+ID+filter.", status_code=303)

    edit_question = None
    if edit_question_id is not None:
        for item in questions:
            if int(item["id"]) == edit_question_id:
                edit_question = item
                break

    admin_count = len([item for item in users if item["role"] == "admin"])
    active_users = len([item for item in users if item["is_active"]])

    return templates.TemplateResponse(
        request=request,
        name="admin.html",
        context={
            "me": me,
            "users": users,
            "test_configs": test_configs,
            "questions": questions,
            "question_config_id": question_filter_id,
            "edit_question": edit_question,
            "message": message,
            "error": error,
            "can_add_admin": me["role"] == "super_admin",
            "active_page": "admin",
            "stats": {
                "total_users": len(users),
                "admin_count": admin_count,
                "active_users": active_users,
                "test_config_count": len(test_configs),
                "question_count": len(questions),
            },
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


@app.get("/admin/users/{user_id}", response_class=HTMLResponse)
def admin_user_details(request: Request, user_id: int, message: str = "", error: str = ""):
    token = get_token(request)
    if not token:
        return redirect_to_login("Please log in first.")
    try:
        me = api_request(token, "GET", "/auth/me")
        if me["role"] not in {"admin", "super_admin"}:
            return RedirectResponse("/dashboard?error=Admin+access+required.", status_code=303)
        user_stats = api_request(token, "GET", f"/admin/users/{user_id}/stats")
    except ValueError as api_error:
        return RedirectResponse(f"/admin?error={quote_plus(str(api_error))}", status_code=303)

    return templates.TemplateResponse(
        request=request,
        name="admin_user.html",
        context={
            "me": me,
            "user_stats": user_stats,
            "message": message,
            "error": error,
            "can_add_admin": me["role"] == "super_admin",
            "active_page": "admin",
        },
    )


@app.post("/admin/users/{user_id}/update")
def admin_update_user(
    request: Request,
    user_id: int,
    username: str = Form(...),
    email: str = Form(...),
    role: str = Form(""),
    credits: int = Form(...),
    is_active: str = Form(...),
    password: str = Form(""),
):
    token = get_token(request)
    if not token:
        return redirect_to_login("Please log in first.")
    payload = {
        "username": username.strip(),
        "email": email.strip(),
        "credits": credits,
        "is_active": is_active == "true",
    }
    role_value = role.strip()
    if role_value and role_value != "super_admin":
        payload["role"] = role_value
    if password.strip():
        payload["password"] = password
    try:
        api_request(token, "PATCH", f"/admin/users/{user_id}", json=payload)
        return RedirectResponse(
            f"/admin/users/{user_id}?message=User+profile+updated+successfully.",
            status_code=303,
        )
    except ValueError as api_error:
        return RedirectResponse(
            f"/admin/users/{user_id}?error={quote_plus(str(api_error))}",
            status_code=303,
        )


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


@app.post("/admin/users/{user_id}/credits")
def admin_add_credits_on_user_page(
    request: Request,
    user_id: int,
    credits_to_add: int = Form(...),
):
    token = get_token(request)
    if not token:
        return redirect_to_login("Please log in first.")
    try:
        api_request(token, "PATCH", f"/admin/users/{user_id}/credits", json={"credits_to_add": credits_to_add})
        return RedirectResponse(
            f"/admin/users/{user_id}?message=Credits+added+successfully.",
            status_code=303,
        )
    except ValueError as api_error:
        return RedirectResponse(
            f"/admin/users/{user_id}?error={quote_plus(str(api_error))}",
            status_code=303,
        )


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


@app.post("/admin/test-configs/{test_config_id}/update")
def admin_update_test_config(
    request: Request,
    test_config_id: int,
    topic_name: str = Form(...),
    level_name: str = Form(...),
    duration_minutes: int = Form(...),
    passing_percent: float = Form(...),
    is_active: str = Form(...),
):
    token = get_token(request)
    if not token:
        return redirect_to_login("Please log in first.")
    payload = {
        "topic_name": topic_name.strip(),
        "level_name": level_name.strip(),
        "duration_seconds": max(1, duration_minutes) * 60,
        "passing_percent": passing_percent,
        "is_active": is_active == "true",
    }
    try:
        api_request(token, "PATCH", f"/admin/test-configs/{test_config_id}", json=payload)
        return RedirectResponse("/admin?message=Test+config+updated.", status_code=303)
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


@app.post("/admin/questions/{question_id}/update")
def admin_update_question(
    request: Request,
    question_id: int,
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
            "PATCH",
            f"/admin/questions/{question_id}",
            json={
                "question_text": question_text.strip(),
                "options": options,
                "correct_index": correct_index,
            },
        )
        return RedirectResponse("/admin?message=Question+updated.", status_code=303)
    except ValueError as api_error:
        return RedirectResponse(f"/admin?error={quote_plus(str(api_error))}", status_code=303)


@app.post("/admin/questions/{question_id}/delete")
def admin_delete_question(request: Request, question_id: int):
    token = get_token(request)
    if not token:
        return redirect_to_login("Please log in first.")
    try:
        api_request(token, "DELETE", f"/admin/questions/{question_id}")
        return RedirectResponse("/admin?message=Question+deleted.", status_code=303)
    except ValueError as api_error:
        return RedirectResponse(f"/admin?error={quote_plus(str(api_error))}", status_code=303)
