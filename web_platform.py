import os
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field


API_BASE_URL = os.getenv("PLATFORM_API_URL", "https://tester-pykb.onrender.com").rstrip("/")
COOKIE_NAME = "platform_token"

API_SESSION = requests.Session()
API_ADAPTER = HTTPAdapter(pool_connections=20, pool_maxsize=50, max_retries=0)
API_SESSION.mount("http://", API_ADAPTER)
API_SESSION.mount("https://", API_ADAPTER)

app = FastAPI(title="Testing Platform Web UI (Vue)", version="2.0.0")
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")


class LoginIn(BaseModel):
    username: str
    password: str


class AdminUserCreateIn(BaseModel):
    username: str = Field(min_length=3)
    email: str
    password: str = Field(min_length=8)
    role: str = "user"
    credits: int = Field(default=0, ge=0)


class AdminUserUpdateIn(BaseModel):
    username: str = Field(min_length=3)
    email: str
    credits: int = Field(ge=0)
    is_active: bool = True
    role: str | None = None
    password: str | None = None


class CreditsIn(BaseModel):
    credits_to_add: int = Field(ge=1)


class ConfigUpdateIn(BaseModel):
    topic_name: str
    level_name: str
    duration_minutes: int = Field(ge=1)
    passing_percent: float = Field(gt=0, le=100)
    is_active: bool = True
    course_id: int | None = None


class ConfigCreateIn(BaseModel):
    topic_name: str
    level_name: str
    duration_minutes: int = Field(ge=1)
    passing_percent: float = Field(gt=0, le=100)
    is_active: bool = True
    course_id: int | None = None


class CourseIn(BaseModel):
    title: str = Field(min_length=1, max_length=180)
    summary: str = ""
    content: str = ""
    is_active: bool = True


class CourseModuleIn(BaseModel):
    course_id: int
    title: str = Field(min_length=1, max_length=180)
    module_type: str = "markdown"
    content: str = ""
    resource_url: str = ""
    order_index: int | None = None
    is_active: bool = True


class TestAccessOverrideIn(BaseModel):
    user_id: int
    test_config_id: int
    grant: bool = True


class QuestionCreateIn(BaseModel):
    test_config_id: int
    section_id: int | None = None
    question_text: str = Field(min_length=5)
    options: list[str] = Field(min_length=2, max_length=10)
    correct_indices: list[int] = Field(min_length=1)


class QuestionUpdateIn(BaseModel):
    section_id: int | None = None
    question_text: str = Field(min_length=5)
    options: list[str] = Field(min_length=2, max_length=10)
    correct_indices: list[int] = Field(min_length=1)


class SectionCreateIn(BaseModel):
    test_config_id: int
    name: str = Field(min_length=1, max_length=120)
    select_count: int = Field(ge=1)
    points_per_question: int = Field(ge=1, le=100)
    requires_full_score: bool = False
    section_type: str = "regular"
    global_question: str | None = None


class SectionUpdateIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    select_count: int = Field(ge=1)
    points_per_question: int = Field(ge=1, le=100)
    requires_full_score: bool = False
    section_type: str | None = None
    global_question: str | None = None


class SectionReorderIn(BaseModel):
    section_ids: list[int] = Field(min_length=1)


class TestBuilderIn(BaseModel):
    topic_name: str
    level_name: str
    duration_minutes: int = Field(ge=1)
    passing_percent: float = Field(gt=0, le=100)
    question_text: str = Field(min_length=5)
    options: list[str] = Field(min_length=2, max_length=10)
    correct_index: int = Field(ge=0)


def normalize_section_type(value: str | None) -> str:
    normalized = str(value or "regular").strip().lower().replace("-", "_")
    if normalized in {"case", "scenario", "case_scenario", "case_scenario_section"}:
        return "case_scenario"
    return "regular"


def section_type_from_payload(section_type: str | None, global_question: str | None) -> str:
    if str(global_question or "").strip():
        return "case_scenario"
    return normalize_section_type(section_type)


def get_token(request: Request) -> str | None:
    return request.cookies.get(COOKIE_NAME)


def require_token(request: Request) -> str:
    token = get_token(request)
    if not token:
        raise HTTPException(status_code=401, detail="Please log in first.")
    return token


def check_desktop_test_participation(request: Request) -> None:
    """Web test participation is allowed; anti-cheat runs in the browser session."""
    return None


def api_request(
    token: str | None,
    method: str,
    path: str,
    *,
    json: dict[str, Any] | None = None,
    data: dict[str, Any] | None = None,
    auth: bool = True,
):
    headers = {}
    if auth:
        if not token:
            raise HTTPException(status_code=401, detail="Please log in first.")
        headers["Authorization"] = f"Bearer {token}"

    try:
        response = API_SESSION.request(
            method=method,
            url=f"{API_BASE_URL}{path}",
            headers=headers,
            json=json,
            data=data,
            timeout=25,
        )
    except requests.RequestException as error:
        raise HTTPException(status_code=503, detail=f"Network error: {error}") from error

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
    if response.status_code == 404 and path.startswith(
        ("/admin/courses", "/admin/course-modules", "/courses/", "/admin/test-access-overrides")
    ):
        detail = (
            "Course API is not available on the configured backend. "
            f"Restart or redeploy platform_api.py, and make sure PLATFORM_API_URL points to that updated API. "
            f"Current API: {API_BASE_URL}"
        )
    raise HTTPException(status_code=response.status_code, detail=detail)


def api_get_many(
    token: str,
    paths_by_key: dict[str, str],
    *,
    optional_keys: set[str] | None = None,
):
    optional = optional_keys or set()
    results: dict[str, Any] = {}
    max_workers = max(1, len(paths_by_key))

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            key: executor.submit(api_request, token, "GET", path)
            for key, path in paths_by_key.items()
        }
        for key, future in futures.items():
            try:
                results[key] = future.result()
            except HTTPException:
                if key in optional:
                    results[key] = []
                else:
                    raise
    return results


def require_admin(request: Request):
    token = require_token(request)
    me = api_request(token, "GET", "/auth/me")
    if me["role"] not in {"admin", "super_admin"}:
        raise HTTPException(status_code=403, detail="Admin access required.")
    return token, me


def render_vue_app(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="vue_index.html",
        context={"api_base_url": API_BASE_URL},
    )


@app.get("/", response_class=HTMLResponse)
def root(request: Request):
    return render_vue_app(request)


@app.get("/dashboard", response_class=HTMLResponse)
def dashboard_page(request: Request):
    return render_vue_app(request)


@app.get("/profile", response_class=HTMLResponse)
def profile_page(request: Request):
    return render_vue_app(request)


@app.get("/admin", response_class=HTMLResponse)
def admin_page(request: Request):
    return render_vue_app(request)


@app.post("/webapi/login")
def webapi_login(payload: LoginIn):
    token_data = api_request(
        None,
        "POST",
        "/auth/login",
        data={"username": payload.username.strip(), "password": payload.password},
        auth=False,
    )
    token = token_data["access_token"]
    me = api_request(token, "GET", "/auth/me")

    response = JSONResponse({"ok": True, "me": me})
    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        httponly=True,
        samesite="lax",
        max_age=60 * 60 * 12,
    )
    return response


@app.post("/webapi/logout")
def webapi_logout():
    response = JSONResponse({"ok": True})
    response.delete_cookie(COOKIE_NAME)
    return response


@app.get("/webapi/session")
def webapi_session(request: Request):
    token = get_token(request)
    if not token:
        return {"authenticated": False}
    try:
        me = api_request(token, "GET", "/auth/me")
    except HTTPException:
        response = JSONResponse({"authenticated": False})
        response.delete_cookie(COOKIE_NAME)
        return response
    return {"authenticated": True, "me": me}


@app.get("/webapi/dashboard")
def webapi_dashboard(request: Request):
    token = require_token(request)
    data = api_get_many(
        token,
        {
            "profile": "/profile/me",
            "social": "/social/dashboard",
            "comments": "/social/comments",
        },
    )
    profile = data["profile"]
    social = data["social"]
    comments = data["comments"]

    comments_by_test: dict[int, list[dict[str, Any]]] = {}
    for item in comments:
        test_id = int(item["test_config_id"])
        comments_by_test.setdefault(test_id, []).append(item)

    return {
        "profile": profile,
        "social_dashboard": social,
        "comments_by_test": comments_by_test,
        "web_test_enabled": False,
    }


@app.get("/webapi/profile")
def webapi_profile(request: Request):
    token = require_token(request)
    data = api_get_many(
        token,
        {
            "profile": "/profile/me",
            "social": "/social/dashboard",
            "me": "/auth/me",
        },
    )
    profile = data["profile"]
    social = data["social"]
    me = data["me"]
    my_results = [item for item in social.get("recent_results", []) if int(item.get("user_id", 0)) == int(me["id"])]
    return {"profile": profile, "my_results": my_results}


@app.post("/webapi/community/comments/{test_config_id}")
def webapi_comment(request: Request, test_config_id: int, payload: dict[str, Any]):
    token = require_token(request)
    content = str(payload.get("content", "")).strip()
    if not content:
        raise HTTPException(status_code=400, detail="Comment cannot be empty.")
    return api_request(token, "POST", f"/social/tests/{test_config_id}/comments", json={"content": content})


@app.post("/webapi/community/follow/{target_user_id}")
def webapi_follow(request: Request, target_user_id: int):
    token = require_token(request)
    return api_request(token, "POST", f"/social/follow/{target_user_id}")


@app.delete("/webapi/community/follow/{target_user_id}")
def webapi_unfollow(request: Request, target_user_id: int):
    token = require_token(request)
    return api_request(token, "DELETE", f"/social/follow/{target_user_id}")


class TestSubmitAnswersIn(BaseModel):
    answers: dict[str, Any]


@app.post("/webapi/tests/start/{test_config_id}")
def webapi_tests_start(request: Request, test_config_id: int):
    token = require_token(request)
    return api_request(token, "POST", f"/tests/start/{test_config_id}")


@app.post("/webapi/tests/submit/{attempt_id}")
def webapi_tests_submit(request: Request, attempt_id: int, payload: TestSubmitAnswersIn):
    token = require_token(request)
    return api_request(token, "POST", f"/tests/submit/{attempt_id}", json=payload.model_dump())


@app.post("/webapi/tests/disqualify/{attempt_id}")
def webapi_tests_disqualify(request: Request, attempt_id: int):
    token = require_token(request)
    return api_request(token, "POST", f"/tests/disqualify/{attempt_id}")


@app.post("/webapi/courses/{course_id}/modules/{module_id}/open")
def webapi_open_course_module(request: Request, course_id: int, module_id: int):
    token = require_token(request)
    return api_request(token, "POST", f"/courses/{course_id}/modules/{module_id}/open")


@app.get("/webapi/community/users/{user_id}/profile")
def webapi_community_user_profile(request: Request, user_id: int):
    token = require_token(request)
    return api_request(token, "GET", f"/social/users/{user_id}/profile")


@app.get("/webapi/admin/overview")
def webapi_admin_overview(request: Request):
    token = require_token(request)
    return api_request(token, "GET", "/admin/overview")


@app.get("/webapi/admin/users/{user_id}/stats")
def webapi_admin_user_stats(request: Request, user_id: int):
    token = require_token(request)
    return api_request(token, "GET", f"/admin/users/{user_id}/stats")


@app.post("/webapi/admin/courses")
def webapi_admin_create_course(request: Request, payload: CourseIn):
    token = require_token(request)
    return api_request(token, "POST", "/admin/courses", json=payload.model_dump())


@app.patch("/webapi/admin/courses/{course_id}")
def webapi_admin_update_course(request: Request, course_id: int, payload: CourseIn):
    token = require_token(request)
    return api_request(token, "PATCH", f"/admin/courses/{course_id}", json=payload.model_dump())


@app.delete("/webapi/admin/courses/{course_id}")
def webapi_admin_delete_course(request: Request, course_id: int):
    token = require_token(request)
    return api_request(token, "DELETE", f"/admin/courses/{course_id}")


@app.post("/webapi/admin/course-modules")
def webapi_admin_create_course_module(request: Request, payload: CourseModuleIn):
    token = require_token(request)
    return api_request(token, "POST", "/admin/course-modules", json=payload.model_dump(exclude_none=True))


@app.patch("/webapi/admin/course-modules/{module_id}")
def webapi_admin_update_course_module(request: Request, module_id: int, payload: CourseModuleIn):
    token = require_token(request)
    data = payload.model_dump(exclude_none=True)
    data.pop("course_id", None)
    return api_request(token, "PATCH", f"/admin/course-modules/{module_id}", json=data)


@app.delete("/webapi/admin/course-modules/{module_id}")
def webapi_admin_delete_course_module(request: Request, module_id: int):
    token = require_token(request)
    return api_request(token, "DELETE", f"/admin/course-modules/{module_id}")


@app.post("/webapi/admin/test-access-overrides")
def webapi_admin_test_access_override(request: Request, payload: TestAccessOverrideIn):
    token = require_token(request)
    return api_request(token, "POST", "/admin/test-access-overrides", json=payload.model_dump())


@app.post("/webapi/admin/users")
def webapi_admin_create_user(request: Request, payload: AdminUserCreateIn):
    token = require_token(request)
    return api_request(token, "POST", "/admin/users", json=payload.model_dump())


@app.patch("/webapi/admin/users/{user_id}")
def webapi_admin_update_user(request: Request, user_id: int, payload: AdminUserUpdateIn):
    token = require_token(request)
    data = payload.model_dump()
    if not data.get("role"):
        data.pop("role", None)
    if not data.get("password"):
        data.pop("password", None)
    return api_request(token, "PATCH", f"/admin/users/{user_id}", json=data)


@app.patch("/webapi/admin/users/{user_id}/credits")
def webapi_admin_add_credits(request: Request, user_id: int, payload: CreditsIn):
    token = require_token(request)
    return api_request(token, "PATCH", f"/admin/users/{user_id}/credits", json=payload.model_dump())


@app.delete("/webapi/admin/users/{user_id}")
def webapi_admin_delete_user(request: Request, user_id: int):
    token = require_token(request)
    return api_request(token, "DELETE", f"/admin/users/{user_id}")


@app.post("/webapi/admin/test-configs")
def webapi_admin_create_config(request: Request, payload: ConfigCreateIn):
    token = require_token(request)
    return api_request(
        token,
        "POST",
        "/admin/test-configs",
        json={
            "topic_name": payload.topic_name.strip(),
            "level_name": payload.level_name.strip(),
            "duration_seconds": payload.duration_minutes * 60,
            "passing_percent": payload.passing_percent,
            "is_active": payload.is_active,
            "course_id": payload.course_id,
        },
    )


@app.patch("/webapi/admin/test-configs/{test_config_id}")
def webapi_admin_update_config(request: Request, test_config_id: int, payload: ConfigUpdateIn):
    token = require_token(request)
    return api_request(
        token,
        "PATCH",
        f"/admin/test-configs/{test_config_id}",
        json={
            "topic_name": payload.topic_name.strip(),
            "level_name": payload.level_name.strip(),
            "duration_seconds": payload.duration_minutes * 60,
            "passing_percent": payload.passing_percent,
            "is_active": payload.is_active,
            "course_id": payload.course_id,
        },
    )


@app.delete("/webapi/admin/test-configs/{test_config_id}")
def webapi_admin_delete_config(request: Request, test_config_id: int):
    token = require_token(request)
    return api_request(token, "DELETE", f"/admin/test-configs/{test_config_id}")


@app.post("/webapi/admin/test-sections")
def webapi_admin_create_section(request: Request, payload: SectionCreateIn):
    token = require_token(request)
    section_type = section_type_from_payload(payload.section_type, payload.global_question)
    result = api_request(
        token,
        "POST",
        "/admin/test-sections",
        json={
            "test_config_id": payload.test_config_id,
            "name": payload.name.strip(),
            "select_count": payload.select_count,
            "points_per_question": payload.points_per_question,
            "requires_full_score": payload.requires_full_score,
            "section_type": section_type,
            "global_question": payload.global_question if section_type == "case_scenario" else None,
        },
    )
    if section_type == "case_scenario" and normalize_section_type(result.get("section_type")) != "case_scenario":
        raise HTTPException(
            status_code=502,
            detail=(
                "The API did not save this as a case-scenario section. "
                "Restart or redeploy platform_api.py so the new section_type field is available."
            ),
        )
    return result


@app.patch("/webapi/admin/test-sections/{section_id}")
def webapi_admin_update_section(request: Request, section_id: int, payload: SectionUpdateIn):
    token = require_token(request)
    section_type = section_type_from_payload(payload.section_type, payload.global_question)
    body = {
        "name": payload.name.strip(),
        "select_count": payload.select_count,
        "points_per_question": payload.points_per_question,
        "requires_full_score": payload.requires_full_score,
    }
    if payload.section_type is not None:
        body["section_type"] = section_type
        body["global_question"] = payload.global_question if section_type == "case_scenario" else None
    result = api_request(
        token,
        "PATCH",
        f"/admin/test-sections/{section_id}",
        json=body,
    )
    if payload.section_type is not None and section_type == "case_scenario" and normalize_section_type(result.get("section_type")) != "case_scenario":
        raise HTTPException(
            status_code=502,
            detail=(
                "The API did not save this as a case-scenario section. "
                "Restart or redeploy platform_api.py so the new section_type field is available."
            ),
        )
    return result


@app.patch("/webapi/admin/test-configs/{test_config_id}/sections/reorder")
def webapi_admin_reorder_sections(request: Request, test_config_id: int, payload: SectionReorderIn):
    token = require_token(request)
    return api_request(
        token,
        "PATCH",
        f"/admin/test-configs/{test_config_id}/sections/reorder",
        json={"section_ids": [int(item) for item in payload.section_ids]},
    )


@app.delete("/webapi/admin/test-sections/{section_id}")
def webapi_admin_delete_section(request: Request, section_id: int):
    token = require_token(request)
    return api_request(token, "DELETE", f"/admin/test-sections/{section_id}")


@app.post("/webapi/admin/questions")
def webapi_admin_create_question(request: Request, payload: QuestionCreateIn):
    token = require_token(request)
    clean_options = [item.strip() for item in payload.options]
    clean_correct_indices = sorted({int(item) for item in payload.correct_indices})
    return api_request(
        token,
        "POST",
        "/admin/questions",
        json={
            "test_config_id": payload.test_config_id,
            "section_id": payload.section_id,
            "question_text": payload.question_text.strip(),
            "options": clean_options,
            "correct_indices": clean_correct_indices,
        },
    )


@app.patch("/webapi/admin/questions/{question_id}")
def webapi_admin_update_question(request: Request, question_id: int, payload: QuestionUpdateIn):
    token = require_token(request)
    clean_options = [item.strip() for item in payload.options]
    clean_correct_indices = sorted({int(item) for item in payload.correct_indices})
    return api_request(
        token,
        "PATCH",
        f"/admin/questions/{question_id}",
        json={
            "section_id": payload.section_id,
            "question_text": payload.question_text.strip(),
            "options": clean_options,
            "correct_indices": clean_correct_indices,
        },
    )


@app.delete("/webapi/admin/questions/{question_id}")
def webapi_admin_delete_question(request: Request, question_id: int):
    token = require_token(request)
    return api_request(token, "DELETE", f"/admin/questions/{question_id}")


@app.post("/webapi/admin/test-builder")
def webapi_admin_test_builder(request: Request, payload: TestBuilderIn):
    token = require_token(request)

    api_request(
        token,
        "POST",
        "/admin/test-configs",
        json={
            "topic_name": payload.topic_name.strip(),
            "level_name": payload.level_name.strip(),
            "duration_seconds": payload.duration_minutes * 60,
            "passing_percent": payload.passing_percent,
            "is_active": True,
        },
    )
    configs = api_request(token, "GET", "/admin/test-configs")
    match = None
    for item in configs:
        if (
            item["topic_name"].strip().lower() == payload.topic_name.strip().lower()
            and item["level_name"].strip().lower() == payload.level_name.strip().lower()
        ):
            match = item
            break
    if match is None:
        raise HTTPException(status_code=500, detail="Unable to locate created test configuration.")

    clean_options = [item.strip() for item in payload.options]
    question = api_request(
        token,
        "POST",
        "/admin/questions",
        json={
            "test_config_id": int(match["id"]),
            "question_text": payload.question_text.strip(),
            "options": clean_options,
            "correct_indices": [payload.correct_index],
        },
    )
    return {"ok": True, "config": match, "question": question}
