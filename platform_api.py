import datetime as dt
import hashlib
import json
import os
import secrets
import smtplib
import shutil
from email.message import EmailMessage
from enum import Enum
from pathlib import Path
from typing import Annotated
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import jwt
from fastapi import Depends, FastAPI, File, HTTPException, Query, Request, UploadFile, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, create_engine, delete, func, inspect, select, text
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, relationship, selectinload, sessionmaker


def normalize_database_url(url: str) -> str:
    value = (url or "").strip()
    if not value:
        return "sqlite:///./platform_backend.db"
    if value.startswith("postgres://"):
        value = value.replace("postgres://", "postgresql://", 1)
    if value.startswith("postgresql+psycopg2://"):
        value = value.replace("postgresql+psycopg2://", "postgresql+psycopg://", 1)
    if value.startswith("postgresql://"):
        value = value.replace("postgresql://", "postgresql+psycopg://", 1)
    if value.startswith("postgresql+psycopg://"):
        split_value = urlsplit(value)
        raw_pairs = parse_qsl(split_value.query, keep_blank_values=True)
        filtered_pairs = []
        for key, query_value in raw_pairs:
            # Some providers show helper params for ORMs/poolers that psycopg/libpq does not accept.
            if key.lower() in {"pgbouncer", "connection_limit", "pool_timeout"}:
                continue
            filtered_pairs.append((key, query_value))
        if not any(key.lower() == "sslmode" for key, _ in filtered_pairs):
            filtered_pairs.append(("sslmode", "require"))
        value = urlunsplit(
            (
                split_value.scheme,
                split_value.netloc,
                split_value.path,
                urlencode(filtered_pairs),
                split_value.fragment,
            )
        )
    return value


DATABASE_URL = normalize_database_url(os.getenv("DATABASE_URL", "sqlite:///./platform_backend.db"))
JWT_SECRET = os.getenv("JWT_SECRET", "change-this-secret-in-production")
JWT_ALGORITHM = "HS256"
JWT_EXPIRE_MINUTES = int(os.getenv("JWT_EXPIRE_MINUTES", "720"))
MODERATOR_INVITE_DAYS = 7
MODERATOR_INVITE_URL = os.getenv("MODERATOR_INVITE_URL", "").strip()

SMTP_HOST = os.getenv("SMTP_HOST", "")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USERNAME = os.getenv("SMTP_USERNAME", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
SMTP_SENDER = os.getenv("SMTP_SENDER", SMTP_USERNAME or "noreply@example.com")
UPLOAD_ROOT = Path(os.getenv("UPLOAD_ROOT", "uploads")).resolve()
COURSE_UPLOAD_DIR = UPLOAD_ROOT / "course_modules"

engine = create_engine(DATABASE_URL, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


def ddl_type(sql_type) -> str:
    return sql_type.compile(dialect=engine.dialect)


class Base(DeclarativeBase):
    pass


class UserRole(str, Enum):
    SUPER_ADMIN = "super_admin"
    ADMIN = "admin"
    MODERATOR = "moderator"
    USER = "user"


class AttemptStatus(str, Enum):
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    DISQUALIFIED = "disqualified"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(300))
    role: Mapped[str] = mapped_column(String(20), default=UserRole.USER.value)
    credits: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=dt.datetime.utcnow)
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)

    attempts: Mapped[list["Attempt"]] = relationship(back_populates="user")


class ModeratorInvite(Base):
    __tablename__ = "moderator_invites"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    created_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=dt.datetime.utcnow)
    expires_at: Mapped[dt.datetime] = mapped_column(DateTime, index=True)
    used_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    moderator_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)


class TestConfig(Base):
    __tablename__ = "test_configs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    topic_name: Mapped[str] = mapped_column(String(120), index=True)
    level_name: Mapped[str] = mapped_column(String(120), index=True)
    duration_seconds: Mapped[int] = mapped_column(Integer, default=900)
    passing_percent: Mapped[float] = mapped_column(Float, default=60.0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    course_id: Mapped[int | None] = mapped_column(ForeignKey("courses.id"), nullable=True, index=True)
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    approval_status: Mapped[str] = mapped_column(String(20), default="approved", index=True)
    approved_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    approved_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)

    questions: Mapped[list["Question"]] = relationship(back_populates="test_config", cascade="all,delete")
    sections: Mapped[list["TestSection"]] = relationship(back_populates="test_config", cascade="all,delete")
    attempts: Mapped[list["Attempt"]] = relationship(back_populates="test_config")
    course: Mapped["Course | None"] = relationship(back_populates="tests")
    author: Mapped["User | None"] = relationship(foreign_keys=[created_by_id])
    approver: Mapped["User | None"] = relationship(foreign_keys=[approved_by_id])


class Course(Base):
    __tablename__ = "courses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(180), index=True)
    summary: Mapped[str] = mapped_column(Text, default="")
    content: Mapped[str] = mapped_column(Text, default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=dt.datetime.utcnow)
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    approval_status: Mapped[str] = mapped_column(String(20), default="approved", index=True)
    approved_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    approved_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)

    tests: Mapped[list[TestConfig]] = relationship(back_populates="course")
    modules: Mapped[list["CourseModule"]] = relationship(back_populates="course", cascade="all,delete")
    author: Mapped["User | None"] = relationship(foreign_keys=[created_by_id])
    approver: Mapped["User | None"] = relationship(foreign_keys=[approved_by_id])


class CourseModule(Base):
    __tablename__ = "course_modules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id"), index=True)
    title: Mapped[str] = mapped_column(String(180), index=True)
    module_type: Mapped[str] = mapped_column(String(40), default="markdown")
    content: Mapped[str] = mapped_column(Text, default="")
    resource_url: Mapped[str] = mapped_column(Text, default="")
    order_index: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    course: Mapped[Course] = relationship(back_populates="modules")


class CourseCompletion(Base):
    __tablename__ = "course_completions"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id"), primary_key=True)
    completed_at: Mapped[dt.datetime] = mapped_column(DateTime, default=dt.datetime.utcnow)


class TestAccessOverride(Base):
    __tablename__ = "test_access_overrides"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)
    test_config_id: Mapped[int] = mapped_column(ForeignKey("test_configs.id"), primary_key=True)
    granted_at: Mapped[dt.datetime] = mapped_column(DateTime, default=dt.datetime.utcnow)


class TestSection(Base):
    __tablename__ = "test_sections"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    test_config_id: Mapped[int] = mapped_column(ForeignKey("test_configs.id"), index=True)
    name: Mapped[str] = mapped_column(String(120), index=True)
    select_count: Mapped[int] = mapped_column(Integer, default=1)
    points_per_question: Mapped[int] = mapped_column(Integer, default=1)
    order_index: Mapped[int] = mapped_column(Integer, default=0)
    requires_full_score: Mapped[bool] = mapped_column(Boolean, default=False)
    section_type: Mapped[str] = mapped_column(String(40), default="regular")
    global_question: Mapped[str | None] = mapped_column(Text, nullable=True)

    test_config: Mapped[TestConfig] = relationship(back_populates="sections")
    questions: Mapped[list["Question"]] = relationship(back_populates="section")


class Question(Base):
    __tablename__ = "questions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    test_config_id: Mapped[int] = mapped_column(ForeignKey("test_configs.id"))
    section_id: Mapped[int | None] = mapped_column(ForeignKey("test_sections.id"), nullable=True)
    question_text: Mapped[str] = mapped_column(Text)
    options_json: Mapped[str] = mapped_column(Text)
    correct_index: Mapped[int] = mapped_column(Integer)

    test_config: Mapped[TestConfig] = relationship(back_populates="questions")
    section: Mapped[TestSection | None] = relationship(back_populates="questions")


class Attempt(Base):
    __tablename__ = "attempts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    test_config_id: Mapped[int] = mapped_column(ForeignKey("test_configs.id"))
    status: Mapped[str] = mapped_column(String(20), default=AttemptStatus.IN_PROGRESS.value)
    started_at: Mapped[dt.datetime] = mapped_column(DateTime, default=dt.datetime.utcnow)
    ended_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    score: Mapped[int] = mapped_column(Integer, default=0)
    total_questions: Mapped[int] = mapped_column(Integer, default=0)
    max_score: Mapped[int] = mapped_column(Integer, default=0)
    selected_question_ids_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    option_orders_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    answers_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    passed: Mapped[bool] = mapped_column(Boolean, default=False)

    user: Mapped[User] = relationship(back_populates="attempts")
    test_config: Mapped[TestConfig] = relationship(back_populates="attempts")


class UserFollow(Base):
    __tablename__ = "user_follows"

    follower_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)
    following_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=dt.datetime.utcnow)


class TestComment(Base):
    __tablename__ = "test_comments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    test_config_id: Mapped[int] = mapped_column(ForeignKey("test_configs.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=dt.datetime.utcnow)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 120_000).hex()
    return f"{salt}${digest}"


def verify_password(password: str, password_hash: str) -> bool:
    try:
        salt, expected = password_hash.split("$", 1)
    except ValueError:
        return False
    actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 120_000).hex()
    return secrets.compare_digest(actual, expected)


def create_access_token(user: User) -> str:
    expires_at = dt.datetime.utcnow() + dt.timedelta(minutes=JWT_EXPIRE_MINUTES)
    payload = {"sub": str(user.id), "role": user.role, "exp": expires_at}
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def hash_invite_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def build_moderator_invite_url(request: Request, token: str) -> str:
    if MODERATOR_INVITE_URL:
        if "{token}" in MODERATOR_INVITE_URL:
            return MODERATOR_INVITE_URL.replace("{token}", token)
        separator = "&" if "?" in MODERATOR_INVITE_URL else "?"
        return f"{MODERATOR_INVITE_URL}{separator}token={token}"
    return f"{str(request.base_url).rstrip('/')}/moderator-register?token={token}"


def get_valid_moderator_invite(db: Session, token: str, *, lock: bool = False) -> ModeratorInvite:
    now = dt.datetime.utcnow()
    query = select(ModeratorInvite).where(ModeratorInvite.token_hash == hash_invite_token(token.strip()))
    if lock:
        query = query.with_for_update()
    invite = db.scalar(query)
    if invite is None or invite.used_at is not None or invite.expires_at < now:
        raise HTTPException(status_code=400, detail="Moderator invite link is invalid, expired, or already used.")
    return invite


def parse_question_payload(options_json: str, fallback_correct_index: int | None = None) -> tuple[list[str], list[int]]:
    try:
        value = json.loads(options_json)
    except json.JSONDecodeError as error:
        raise HTTPException(status_code=500, detail="Invalid options data in database.") from error
    options: list[str]
    correct_indices: list[int]
    if isinstance(value, list):
        options = [str(item) for item in value]
        fallback = 0 if fallback_correct_index is None else int(fallback_correct_index)
        correct_indices = [fallback]
    elif isinstance(value, dict):
        raw_options = value.get("options")
        raw_correct_indices = value.get("correct_indices", [])
        if not isinstance(raw_options, list):
            raise HTTPException(status_code=500, detail="Invalid options format in database.")
        if not isinstance(raw_correct_indices, list):
            raise HTTPException(status_code=500, detail="Invalid correct answer format in database.")
        options = [str(item) for item in raw_options]
        correct_indices = []
        for item in raw_correct_indices:
            try:
                index_value = int(item)
            except (TypeError, ValueError):
                continue
            if index_value >= 0:
                correct_indices.append(index_value)
        if not correct_indices:
            fallback = 0 if fallback_correct_index is None else int(fallback_correct_index)
            correct_indices = [fallback]
        correct_indices = sorted(set(correct_indices))
    else:
        raise HTTPException(status_code=500, detail="Invalid options format in database.")

    if not options:
        raise HTTPException(status_code=500, detail="Question options are empty in database.")
    valid_indices = [index for index in correct_indices if index < len(options)]
    if not valid_indices:
        valid_indices = [0]
    return options, valid_indices


def build_question_payload(options: list[str], correct_indices: list[int]) -> str:
    unique_indices = sorted(set(int(item) for item in correct_indices if int(item) >= 0))
    return json.dumps({"options": options, "correct_indices": unique_indices})


def parse_selected_question_ids(raw_value: str | None) -> list[int]:
    if not raw_value:
        return []
    try:
        value = json.loads(raw_value)
    except json.JSONDecodeError:
        return []
    if not isinstance(value, list):
        return []
    ids = []
    for item in value:
        try:
            ids.append(int(item))
        except (TypeError, ValueError):
            continue
    return ids


def parse_option_orders(raw_value: str | None) -> dict[int, list[int]]:
    if not raw_value:
        return {}
    try:
        value = json.loads(raw_value)
    except json.JSONDecodeError:
        return {}
    if not isinstance(value, dict):
        return {}
    result: dict[int, list[int]] = {}
    for raw_question_id, raw_order in value.items():
        try:
            question_id = int(raw_question_id)
        except (TypeError, ValueError):
            continue
        if not isinstance(raw_order, list):
            continue
        order = []
        for item in raw_order:
            try:
                order.append(int(item))
            except (TypeError, ValueError):
                continue
        if order:
            result[question_id] = order
    return result


def parse_attempt_answers(raw_value: str | None) -> dict[int, int | list[int]]:
    if not raw_value:
        return {}
    try:
        value = json.loads(raw_value)
    except json.JSONDecodeError:
        return {}
    if not isinstance(value, dict):
        return {}
    result: dict[int, int | list[int]] = {}
    for raw_question_id, raw_answer in value.items():
        try:
            question_id = int(raw_question_id)
        except (TypeError, ValueError):
            continue
        if isinstance(raw_answer, list):
            selected = []
            for item in raw_answer:
                try:
                    index = int(item)
                except (TypeError, ValueError):
                    continue
                if index >= 0:
                    selected.append(index)
            result[question_id] = sorted(set(selected))
            continue
        try:
            index = int(raw_answer)
        except (TypeError, ValueError):
            continue
        result[question_id] = index
    return result


def shuffled_option_order(option_count: int, randomizer: secrets.SystemRandom) -> list[int]:
    order = list(range(option_count))
    randomizer.shuffle(order)
    if option_count > 1 and order == list(range(option_count)):
        order = order[1:] + order[:1]
    return order


def question_points(question: Question) -> int:
    return question.section.points_per_question if question.section is not None else 1


def section_requires_full_score(question: Question) -> bool:
    return bool(question.section is not None and question.section.requires_full_score)


def parse_options(options_json: str, fallback_correct_index: int | None = None) -> list[str]:
    options, _ = parse_question_payload(options_json, fallback_correct_index)
    return options


def normalize_section_type(value: str | None) -> str:
    normalized = str(value or "regular").strip().lower().replace("-", "_")
    if normalized in {"case", "scenario", "case_scenario", "case_scenario_section"}:
        return "case_scenario"
    return "regular"


def section_type_from_payload(section_type: str | None, global_question: str | None) -> str:
    if str(global_question or "").strip():
        return "case_scenario"
    return normalize_section_type(section_type)


def normalize_global_question(section_type: str, value: str | None) -> str | None:
    cleaned = str(value or "").strip()
    if section_type != "case_scenario":
        return None
    return cleaned or None


def send_pass_notification_email(to_email: str, username: str, topic_name: str, level_name: str, score_text: str):
    if not SMTP_HOST or not SMTP_USERNAME or not SMTP_PASSWORD:
        return

    message = EmailMessage()
    message["Subject"] = "Test Passed Successfully"
    message["From"] = SMTP_SENDER
    message["To"] = to_email
    message.set_content(
        "Congratulations!\n\n"
        f"User: {username}\n"
        f"Topic: {topic_name}\n"
        f"Level: {level_name}\n"
        f"Score: {score_text}\n\n"
        "You have successfully passed the test."
    )

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=20) as smtp:
            smtp.starttls()
            smtp.login(SMTP_USERNAME, SMTP_PASSWORD)
            smtp.send_message(message)
    except Exception:
        # Notification errors should not break main test flow.
        return


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"


class BootstrapSuperAdminIn(BaseModel):
    username: str = Field(min_length=3, max_length=120)
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class UserCreateIn(BaseModel):
    username: str = Field(min_length=3, max_length=120)
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    role: UserRole = UserRole.USER
    credits: int = Field(default=0, ge=0)


class ModeratorInviteOut(BaseModel):
    id: int
    token: str
    registration_url: str
    expires_at: dt.datetime
    used_at: dt.datetime | None = None


class ModeratorInviteStatusOut(BaseModel):
    valid: bool
    expires_at: dt.datetime | None = None


class ModeratorInviteRegisterIn(BaseModel):
    token: str = Field(min_length=20, max_length=200)
    username: str = Field(min_length=3, max_length=120)
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class UserOut(BaseModel):
    id: int
    username: str
    email: EmailStr
    role: UserRole
    credits: int
    is_active: bool


class CreditUpdateIn(BaseModel):
    credits_to_add: int = Field(ge=1)


class TestConfigCreateIn(BaseModel):
    topic_name: str = Field(min_length=1, max_length=120)
    level_name: str = Field(min_length=1, max_length=120)
    duration_seconds: int = Field(ge=30, le=14_400)
    passing_percent: float = Field(ge=1, le=100)
    is_active: bool = True
    course_id: int | None = None


class TestConfigOut(BaseModel):
    id: int
    topic_name: str
    level_name: str
    duration_seconds: int
    passing_percent: float
    is_active: bool
    question_count: int
    bank_question_count: int
    section_count: int
    course_id: int | None = None
    course_title: str | None = None
    course_completed: bool = False
    access_override: bool = False
    can_start: bool = True
    locked_reason: str | None = None
    author_id: int | None = None
    author_username: str | None = None
    approval_status: str = "approved"
    approved_by_id: int | None = None
    approved_by_username: str | None = None
    approved_at: dt.datetime | None = None


class CourseCreateIn(BaseModel):
    title: str = Field(min_length=1, max_length=180)
    summary: str = ""
    content: str = ""
    is_active: bool = True


class CourseUpdateIn(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=180)
    summary: str | None = None
    content: str | None = None
    is_active: bool | None = None


class CourseModuleCreateIn(BaseModel):
    course_id: int
    title: str = Field(min_length=1, max_length=180)
    module_type: str = "markdown"
    content: str = ""
    resource_url: str = ""
    order_index: int | None = None
    is_active: bool = True


class CourseModuleUpdateIn(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=180)
    module_type: str | None = None
    content: str | None = None
    resource_url: str | None = None
    order_index: int | None = None
    is_active: bool | None = None


class CourseModuleOut(BaseModel):
    id: int
    course_id: int
    title: str
    module_type: str
    content: str
    resource_url: str
    order_index: int
    is_active: bool
    is_last: bool = False


class CourseOut(BaseModel):
    id: int
    title: str
    summary: str
    content: str
    is_active: bool
    completed: bool = False
    author_id: int | None = None
    author_username: str | None = None
    approval_status: str = "approved"
    approved_by_id: int | None = None
    approved_by_username: str | None = None
    approved_at: dt.datetime | None = None
    modules: list[CourseModuleOut] = Field(default_factory=list)
    linked_tests: list[TestConfigOut] = Field(default_factory=list)


class TestAccessOverrideIn(BaseModel):
    user_id: int
    test_config_id: int
    grant: bool = True


class ContentApprovalIn(BaseModel):
    approved: bool = True


class CourseModuleFileOut(BaseModel):
    url: str
    filename: str


class TestSectionCreateIn(BaseModel):
    test_config_id: int
    name: str = Field(min_length=1, max_length=120)
    select_count: int = Field(ge=1)
    points_per_question: int = Field(ge=1, le=100)
    requires_full_score: bool = False
    section_type: str = "regular"
    global_question: str | None = None


class TestSectionUpdateIn(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    select_count: int | None = Field(default=None, ge=1)
    points_per_question: int | None = Field(default=None, ge=1, le=100)
    requires_full_score: bool | None = None
    section_type: str | None = None
    global_question: str | None = None


class TestSectionReorderIn(BaseModel):
    section_ids: list[int] = Field(min_length=1)


class TestSectionOut(BaseModel):
    id: int
    test_config_id: int
    name: str
    select_count: int
    points_per_question: int
    order_index: int
    requires_full_score: bool
    section_type: str
    global_question: str | None = None
    question_count: int


class QuestionCreateIn(BaseModel):
    test_config_id: int
    section_id: int | None = None
    question_text: str = Field(min_length=5)
    options: list[str] = Field(min_length=2, max_length=10)
    correct_indices: list[int] = Field(min_length=1)


class QuestionPublicOut(BaseModel):
    id: int
    question_text: str
    options: list[str]
    allow_multiple: bool = False
    section_id: int | None = None
    section_name: str | None = None
    section_type: str = "regular"
    global_question: str | None = None


class QuestionAdminOut(QuestionPublicOut):
    test_config_id: int
    section_id: int | None = None
    correct_index: int
    correct_indices: list[int]


class TestStartOut(BaseModel):
    attempt_id: int
    duration_seconds: int
    passing_percent: float
    remaining_credits: int
    questions: list[QuestionPublicOut]


class SubmitAttemptIn(BaseModel):
    answers: dict[int, int | list[int]]


class SubmitAttemptOut(BaseModel):
    attempt_id: int
    passed: bool
    score: int
    total_questions: int
    success_percent: float
    remaining_credits: int


class ProfileStatsOut(BaseModel):
    user: UserOut
    tests_done: int
    passed_tests: int
    failed_tests: int
    success_rate_percent: float


class AttemptAnswerAdminOut(BaseModel):
    question_id: int
    question_text: str
    section_name: str | None = None
    selected_answers: list[str]
    correct_answers: list[str]
    is_correct: bool
    was_answered: bool


class AttemptAdminOut(BaseModel):
    id: int
    status: str
    score: int
    total_questions: int
    passed: bool
    started_at: dt.datetime
    ended_at: dt.datetime | None
    topic_name: str
    level_name: str
    answers: list[AttemptAnswerAdminOut] = Field(default_factory=list)


class UserAdminStatsOut(BaseModel):
    user: UserOut
    tests_done: int
    passed_tests: int
    failed_tests: int
    success_rate_percent: float
    attempts: list[AttemptAdminOut]


class AdminOverviewOut(BaseModel):
    users: list[UserOut]
    test_configs: list[TestConfigOut]
    courses: list[CourseOut]
    sections: list[TestSectionOut]
    questions: list[QuestionAdminOut]


class UserAdminUpdateIn(BaseModel):
    username: str | None = Field(default=None, min_length=3, max_length=120)
    email: EmailStr | None = None
    role: UserRole | None = None
    credits: int | None = Field(default=None, ge=0)
    is_active: bool | None = None
    password: str | None = Field(default=None, min_length=8, max_length=128)


class TestConfigUpdateIn(BaseModel):
    topic_name: str | None = Field(default=None, min_length=1, max_length=120)
    level_name: str | None = Field(default=None, min_length=1, max_length=120)
    duration_seconds: int | None = Field(default=None, ge=30, le=14_400)
    passing_percent: float | None = Field(default=None, ge=1, le=100)
    is_active: bool | None = None
    course_id: int | None = None


class QuestionUpdateIn(BaseModel):
    section_id: int | None = None
    question_text: str | None = Field(default=None, min_length=5)
    options: list[str] | None = Field(default=None, min_length=2, max_length=10)
    correct_indices: list[int] | None = None


class SocialCommentCreateIn(BaseModel):
    content: str = Field(min_length=1, max_length=1000)


class SocialCommentOut(BaseModel):
    id: int
    test_config_id: int
    user_id: int
    username: str
    content: str
    created_at: dt.datetime


class SocialActiveUserOut(BaseModel):
    id: int
    username: str
    role: UserRole
    tests_done: int
    success_rate_percent: float
    follower_count: int


class SocialResultOut(BaseModel):
    attempt_id: int
    user_id: int
    username: str
    user_role: UserRole | None = None
    topic_name: str
    level_name: str
    score: int
    total_questions: int
    passed: bool
    success_percent: float
    ended_at: dt.datetime | None


class SocialDashboardOut(BaseModel):
    courses: list[CourseOut]
    tests: list[TestConfigOut]
    active_users: list[SocialActiveUserOut]
    recent_results: list[SocialResultOut]
    following_user_ids: list[int]


class SocialProfileUserOut(BaseModel):
    id: int
    username: str
    role: UserRole


class SocialUserProfileOut(BaseModel):
    user: SocialProfileUserOut
    tests_done: int
    passed_tests: int
    failed_tests: int
    success_rate_percent: float
    recent_results: list[SocialResultOut]


def serialize_user(user: User) -> UserOut:
    return UserOut(
        id=user.id,
        username=user.username,
        email=user.email,
        role=UserRole(user.role),
        credits=user.credits,
        is_active=user.is_active,
    )


def serialize_question_admin(question: Question) -> QuestionAdminOut:
    options, correct_indices = parse_question_payload(question.options_json, question.correct_index)
    return QuestionAdminOut(
        id=question.id,
        test_config_id=question.test_config_id,
        section_id=question.section_id,
        section_name=question.section.name if question.section is not None else None,
        section_type=(question.section.section_type or "regular") if question.section is not None else "regular",
        global_question=question.section.global_question if question.section is not None else None,
        question_text=question.question_text,
        options=options,
        correct_index=correct_indices[0],
        correct_indices=correct_indices,
    )


def configured_question_count(config: TestConfig) -> int:
    if not config.sections:
        return len(config.questions)
    return sum(min(max(section.select_count, 0), len(section.questions)) for section in config.sections)


def user_completed_course_ids(db: Session, user_id: int) -> set[int]:
    rows = db.scalars(select(CourseCompletion.course_id).where(CourseCompletion.user_id == user_id)).all()
    return {int(item) for item in rows}


def user_override_test_ids(db: Session, user_id: int) -> set[int]:
    rows = db.scalars(select(TestAccessOverride.test_config_id).where(TestAccessOverride.user_id == user_id)).all()
    return {int(item) for item in rows}


def serialize_test_config(
    config: TestConfig,
    *,
    completed_course_ids: set[int] | None = None,
    override_test_ids: set[int] | None = None,
) -> TestConfigOut:
    completed_course_ids = completed_course_ids or set()
    override_test_ids = override_test_ids or set()
    course_id = int(config.course_id) if config.course_id else None
    course_completed = bool(course_id and course_id in completed_course_ids)
    access_override = int(config.id) in override_test_ids
    can_start = not course_id or course_completed or access_override
    return TestConfigOut(
        id=config.id,
        topic_name=config.topic_name,
        level_name=config.level_name,
        duration_seconds=config.duration_seconds,
        passing_percent=config.passing_percent,
        is_active=config.is_active,
        question_count=configured_question_count(config),
        bank_question_count=len(config.questions),
        section_count=len(config.sections),
        course_id=course_id,
        course_title=config.course.title if config.course is not None else None,
        course_completed=course_completed,
        access_override=access_override,
        can_start=can_start,
        locked_reason=None if can_start else "Finish the linked course before starting this test.",
        author_id=config.created_by_id,
        author_username=config.author.username if config.author is not None else None,
        approval_status=config.approval_status or "approved",
        approved_by_id=config.approved_by_id,
        approved_by_username=config.approver.username if config.approver is not None else None,
        approved_at=config.approved_at,
    )


def normalize_module_type(value: str | None) -> str:
    normalized = str(value or "markdown").strip().lower().replace("-", "_")
    if normalized in {"doc", "docs", "document", "pdf"}:
        return "document"
    if normalized in {"ppt", "pptx", "presentation", "slides"}:
        return "presentation"
    if normalized in {"video", "youtube", "vimeo"}:
        return "video"
    return "markdown"


def serialize_course_module(module: CourseModule, *, last_module_id: int | None = None) -> CourseModuleOut:
    return CourseModuleOut(
        id=module.id,
        course_id=module.course_id,
        title=module.title,
        module_type=normalize_module_type(module.module_type),
        content=module.content or "",
        resource_url=module.resource_url or "",
        order_index=module.order_index,
        is_active=module.is_active,
        is_last=bool(last_module_id and module.id == last_module_id),
    )


def serialize_course(
    course: Course,
    *,
    completed_course_ids: set[int] | None = None,
    override_test_ids: set[int] | None = None,
    include_tests: bool = True,
    managed_by_user_id: int | None = None,
    public_only: bool = False,
) -> CourseOut:
    completed_course_ids = completed_course_ids or set()
    override_test_ids = override_test_ids or set()
    tests = []
    if include_tests:
        course_tests = course.tests
        if managed_by_user_id is not None:
            course_tests = [test for test in course_tests if test.created_by_id == managed_by_user_id]
        if public_only:
            course_tests = [test for test in course_tests if is_content_published(test)]
        tests = [
            serialize_test_config(
                test,
                completed_course_ids=completed_course_ids,
                override_test_ids=override_test_ids,
            )
            for test in sorted(course_tests, key=lambda item: (item.topic_name.lower(), item.level_name.lower(), item.id))
        ]
    active_modules = sorted(
        [module for module in course.modules if module.is_active],
        key=lambda item: (item.order_index, item.id),
    )
    last_module_id = active_modules[-1].id if active_modules else None
    modules = [
        serialize_course_module(module, last_module_id=last_module_id)
        for module in sorted(course.modules, key=lambda item: (item.order_index, item.id))
    ]
    return CourseOut(
        id=course.id,
        title=course.title,
        summary=course.summary or "",
        content=course.content or "",
        is_active=course.is_active,
        completed=course.id in completed_course_ids,
        author_id=course.created_by_id,
        author_username=course.author.username if course.author is not None else None,
        approval_status=course.approval_status or "approved",
        approved_by_id=course.approved_by_id,
        approved_by_username=course.approver.username if course.approver is not None else None,
        approved_at=course.approved_at,
        modules=modules,
        linked_tests=tests,
    )


def serialize_test_section(section: TestSection) -> TestSectionOut:
    return TestSectionOut(
        id=section.id,
        test_config_id=section.test_config_id,
        name=section.name,
        select_count=section.select_count,
        points_per_question=section.points_per_question,
        order_index=section.order_index,
        requires_full_score=section.requires_full_score,
        section_type=section.section_type or "regular",
        global_question=section.global_question,
        question_count=len(section.questions),
    )


def can_manage_target_user(current_user: User, target_user: User) -> bool:
    if current_user.role == UserRole.SUPER_ADMIN.value:
        return True
    if current_user.role == UserRole.ADMIN.value:
        return target_user.role in {UserRole.USER.value, UserRole.MODERATOR.value}
    return False


def can_manage_content(current_user: User, item: TestConfig | Course) -> bool:
    if current_user.role in {UserRole.SUPER_ADMIN.value, UserRole.ADMIN.value}:
        return True
    if current_user.role == UserRole.MODERATOR.value:
        return item.created_by_id == current_user.id
    return False


def is_content_published(item: TestConfig | Course) -> bool:
    return bool(item.is_active) and (item.approval_status or "approved") == "approved"


def approval_fields_for_create(current_user: User) -> dict[str, object]:
    if current_user.role == UserRole.MODERATOR.value:
        return {"approval_status": "pending", "approved_by_id": None, "approved_at": None}
    return {
        "approval_status": "approved",
        "approved_by_id": current_user.id,
        "approved_at": dt.datetime.utcnow(),
    }


def mark_pending_after_moderator_edit(current_user: User, item: TestConfig | Course) -> None:
    if current_user.role == UserRole.MODERATOR.value:
        item.approval_status = "pending"
        item.approved_by_id = None
        item.approved_at = None


def require_content_access(current_user: User, item: TestConfig | Course, label: str) -> None:
    if not can_manage_content(current_user, item):
        raise HTTPException(status_code=403, detail=f"You can only manage {label} that you created.")


def visible_content_query(current_user: User, model):
    query = select(model)
    if current_user.role == UserRole.MODERATOR.value:
        query = query.where(model.created_by_id == current_user.id)
    return query


def build_attempt_answer_rows(attempt: Attempt, config: TestConfig | None) -> list[AttemptAnswerAdminOut]:
    if config is None or not attempt.answers_json:
        return []
    selected_ids = parse_selected_question_ids(attempt.selected_question_ids_json)
    question_by_id = {question.id: question for question in config.questions}
    if selected_ids:
        questions = [question_by_id[question_id] for question_id in selected_ids if question_id in question_by_id]
    else:
        questions = list(config.questions)

    answers = parse_attempt_answers(attempt.answers_json)
    option_orders = parse_option_orders(attempt.option_orders_json)
    rows: list[AttemptAnswerAdminOut] = []
    for question in questions:
        options, correct_indices = parse_question_payload(question.options_json, question.correct_index)
        option_order = option_orders.get(question.id) or list(range(len(options)))
        visible_options = [options[index] for index in option_order if 0 <= index < len(options)]
        raw_selected = answers.get(question.id, -1)
        if isinstance(raw_selected, list):
            selected_display_indices = sorted({int(item) for item in raw_selected if int(item) >= 0})
        elif isinstance(raw_selected, int) and raw_selected >= 0:
            selected_display_indices = [raw_selected]
        else:
            selected_display_indices = []

        selected_original_indices = sorted(
            {
                option_order[index]
                for index in selected_display_indices
                if 0 <= index < len(option_order)
            }
        )
        correct_display_indices = sorted(
            option_order.index(index)
            for index in correct_indices
            if index in option_order
        )
        rows.append(
            AttemptAnswerAdminOut(
                question_id=question.id,
                question_text=question.question_text,
                section_name=question.section.name if question.section is not None else None,
                selected_answers=[
                    visible_options[index]
                    for index in selected_display_indices
                    if 0 <= index < len(visible_options)
                ],
                correct_answers=[
                    visible_options[index]
                    for index in correct_display_indices
                    if 0 <= index < len(visible_options)
                ],
                is_correct=selected_original_indices == correct_indices,
                was_answered=bool(selected_display_indices),
            )
        )
    return rows


def build_user_admin_stats(db: Session, user: User) -> UserAdminStatsOut:
    attempts = db.scalars(select(Attempt).where(Attempt.user_id == user.id).order_by(Attempt.id.desc())).all()
    finalized_attempts = [item for item in attempts if item.status != AttemptStatus.IN_PROGRESS.value]
    tests_done = len(finalized_attempts)
    passed_tests = len([item for item in finalized_attempts if item.passed])
    failed_tests = tests_done - passed_tests
    success_rate = (passed_tests / tests_done * 100) if tests_done else 0.0

    config_ids = {item.test_config_id for item in attempts}
    config_map = {}
    if config_ids:
        configs = db.scalars(select(TestConfig).where(TestConfig.id.in_(config_ids))).all()
        config_map = {config.id: config for config in configs}

    attempt_rows = []
    for item in attempts:
        config = config_map.get(item.test_config_id)
        attempt_rows.append(
            AttemptAdminOut(
                id=item.id,
                status=item.status,
                score=item.score,
                total_questions=item.max_score or item.total_questions,
                passed=item.passed,
                started_at=item.started_at,
                ended_at=item.ended_at,
                topic_name=config.topic_name if config else "Unknown",
                level_name=config.level_name if config else "Unknown",
                answers=build_attempt_answer_rows(item, config),
            )
        )

    return UserAdminStatsOut(
        user=serialize_user(user),
        tests_done=tests_done,
        passed_tests=passed_tests,
        failed_tests=failed_tests,
        success_rate_percent=round(success_rate, 2),
        attempts=attempt_rows,
    )


def serialize_social_comment(comment: TestComment, username: str) -> SocialCommentOut:
    return SocialCommentOut(
        id=comment.id,
        test_config_id=comment.test_config_id,
        user_id=comment.user_id,
        username=username,
        content=comment.content,
        created_at=comment.created_at,
    )


def build_social_dashboard(db: Session, current_user: User) -> SocialDashboardOut:
    completed_course_ids = user_completed_course_ids(db, current_user.id)
    override_test_ids = user_override_test_ids(db, current_user.id)
    courses = db.scalars(
        select(Course)
        .options(
            selectinload(Course.modules),
            selectinload(Course.tests).selectinload(TestConfig.questions),
            selectinload(Course.tests).selectinload(TestConfig.sections).selectinload(TestSection.questions),
            selectinload(Course.tests).selectinload(TestConfig.course),
            selectinload(Course.tests).selectinload(TestConfig.author),
            selectinload(Course.tests).selectinload(TestConfig.approver),
            selectinload(Course.author),
            selectinload(Course.approver),
        )
        .where(Course.is_active.is_(True), Course.approval_status == "approved")
        .order_by(Course.title.asc(), Course.id.asc())
    ).all()
    tests = db.scalars(
        select(TestConfig)
        .options(
            selectinload(TestConfig.questions),
            selectinload(TestConfig.sections).selectinload(TestSection.questions),
            selectinload(TestConfig.course),
            selectinload(TestConfig.author),
            selectinload(TestConfig.approver),
        )
        .where(TestConfig.is_active.is_(True), TestConfig.approval_status == "approved")
        .order_by(TestConfig.topic_name.asc(), TestConfig.level_name.asc())
    ).all()
    tests_out = [
        serialize_test_config(item, completed_course_ids=completed_course_ids, override_test_ids=override_test_ids)
        for item in tests
        if item.course_id is None or (item.course is not None and is_content_published(item.course))
    ]
    courses_out = [
        serialize_course(
            item,
            completed_course_ids=completed_course_ids,
            override_test_ids=override_test_ids,
            public_only=True,
        )
        for item in courses
    ]

    following_ids = db.scalars(
        select(UserFollow.following_id).where(UserFollow.follower_id == current_user.id)
    ).all()
    following_user_ids = [int(item) for item in following_ids]

    recent_attempts = db.scalars(
        select(Attempt)
        .where(Attempt.status != AttemptStatus.IN_PROGRESS.value)
        .order_by(Attempt.ended_at.desc(), Attempt.id.desc())
        .limit(50)
    ).all()
    user_ids_from_attempts = {item.user_id for item in recent_attempts}
    config_ids_from_attempts = {item.test_config_id for item in recent_attempts}

    user_map = {}
    if user_ids_from_attempts:
        users = db.scalars(select(User).where(User.id.in_(user_ids_from_attempts))).all()
        user_map = {item.id: item for item in users}

    config_map = {}
    if config_ids_from_attempts:
        configs = db.scalars(select(TestConfig).where(TestConfig.id.in_(config_ids_from_attempts))).all()
        config_map = {item.id: item for item in configs}

    recent_results = []
    for attempt in recent_attempts:
        user = user_map.get(attempt.user_id)
        config = config_map.get(attempt.test_config_id)
        if user is None or config is None:
            continue
        total = max(attempt.max_score or attempt.total_questions, 1)
        success_percent = (attempt.score / total) * 100
        recent_results.append(
            SocialResultOut(
                attempt_id=attempt.id,
                user_id=user.id,
                username=user.username,
                user_role=UserRole(user.role),
                topic_name=config.topic_name,
                level_name=config.level_name,
                score=attempt.score,
                total_questions=attempt.max_score or attempt.total_questions,
                passed=attempt.passed,
                success_percent=round(success_percent, 2),
                ended_at=attempt.ended_at,
            )
        )

    now = dt.datetime.utcnow()
    active_cutoff = now - dt.timedelta(days=30)
    active_ids = db.scalars(
        select(Attempt.user_id)
        .where(Attempt.started_at >= active_cutoff)
        .group_by(Attempt.user_id)
    ).all()
    active_user_ids = set(int(item) for item in active_ids)
    if current_user.id not in active_user_ids:
        active_user_ids.add(current_user.id)

    active_users = []
    if active_user_ids:
        users = db.scalars(
            select(User).where(User.id.in_(active_user_ids), User.is_active.is_(True)).order_by(User.username.asc())
        ).all()
        follower_counts = {
            int(row[0]): int(row[1])
            for row in db.execute(
                select(UserFollow.following_id, func.count(UserFollow.follower_id))
                .where(UserFollow.following_id.in_(active_user_ids))
                .group_by(UserFollow.following_id)
            ).all()
        }
        attempts_by_user = {
            int(row[0]): int(row[1])
            for row in db.execute(
                select(Attempt.user_id, func.count(Attempt.id))
                .where(Attempt.user_id.in_(active_user_ids), Attempt.status != AttemptStatus.IN_PROGRESS.value)
                .group_by(Attempt.user_id)
            ).all()
        }
        passed_by_user = {
            int(row[0]): int(row[1])
            for row in db.execute(
                select(Attempt.user_id, func.count(Attempt.id))
                .where(
                    Attempt.user_id.in_(active_user_ids),
                    Attempt.status != AttemptStatus.IN_PROGRESS.value,
                    Attempt.passed.is_(True),
                )
                .group_by(Attempt.user_id)
            ).all()
        }

        for user in users:
            tests_done = attempts_by_user.get(user.id, 0)
            passed = passed_by_user.get(user.id, 0)
            success_rate = (passed / tests_done * 100) if tests_done else 0.0
            active_users.append(
                SocialActiveUserOut(
                    id=user.id,
                    username=user.username,
                    role=UserRole(user.role),
                    tests_done=tests_done,
                    success_rate_percent=round(success_rate, 2),
                    follower_count=follower_counts.get(user.id, 0),
                )
            )
        active_users.sort(key=lambda item: (-item.tests_done, item.username.lower()))

    return SocialDashboardOut(
        courses=courses_out,
        tests=tests_out,
        active_users=active_users[:30],
        recent_results=recent_results,
        following_user_ids=following_user_ids,
    )


def build_social_user_profile(db: Session, target_user: User) -> SocialUserProfileOut:
    attempts = db.scalars(
        select(Attempt)
        .where(Attempt.user_id == target_user.id, Attempt.status != AttemptStatus.IN_PROGRESS.value)
        .order_by(Attempt.id.desc())
    ).all()

    tests_done = len(attempts)
    passed_tests = len([item for item in attempts if item.passed])
    failed_tests = tests_done - passed_tests
    success_rate = (passed_tests / tests_done * 100) if tests_done else 0.0

    config_ids = {item.test_config_id for item in attempts}
    config_map: dict[int, TestConfig] = {}
    if config_ids:
        configs = db.scalars(select(TestConfig).where(TestConfig.id.in_(config_ids))).all()
        config_map = {config.id: config for config in configs}

    recent_results: list[SocialResultOut] = []
    for item in attempts[:20]:
        config = config_map.get(item.test_config_id)
        topic_name = config.topic_name if config is not None else "Unknown Topic"
        level_name = config.level_name if config is not None else "Unknown Level"
        total = item.max_score or item.total_questions
        success_percent = (item.score / total * 100) if total else 0.0
        recent_results.append(
            SocialResultOut(
                attempt_id=item.id,
                user_id=target_user.id,
                username=target_user.username,
                user_role=UserRole(target_user.role),
                topic_name=topic_name,
                level_name=level_name,
                score=item.score,
                total_questions=total,
                passed=item.passed,
                success_percent=round(success_percent, 2),
                ended_at=item.ended_at,
            )
        )

    return SocialUserProfileOut(
        user=SocialProfileUserOut(id=target_user.id, username=target_user.username, role=UserRole(target_user.role)),
        tests_done=tests_done,
        passed_tests=passed_tests,
        failed_tests=failed_tests,
        success_rate_percent=round(success_rate, 2),
        recent_results=recent_results,
    )


def get_current_user(
    token: Annotated[str, Depends(oauth2_scheme)],
    db: Annotated[Session, Depends(get_db)],
) -> User:
    bad_auth = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid authentication credentials.",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        user_id = int(payload.get("sub", "0"))
    except Exception as error:
        raise bad_auth from error
    user = db.get(User, user_id)
    if user is None or not user.is_active:
        raise bad_auth
    return user


def require_roles(*allowed_roles: UserRole):
    allowed_values = {role.value for role in allowed_roles}

    def _check(current_user: Annotated[User, Depends(get_current_user)]) -> User:
        if current_user.role not in allowed_values:
            raise HTTPException(status_code=403, detail="You do not have permission for this action.")
        return current_user

    return _check


app = FastAPI(
    title="Testing Platform API",
    description=(
        "Central API for desktop and web clients. "
        "Includes shared users, admin/super-admin RBAC, credits, test timers, pass-rate rules, and profile stats."
    ),
    version="1.0.0",
)
UPLOAD_ROOT.mkdir(parents=True, exist_ok=True)
COURSE_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=str(UPLOAD_ROOT)), name="uploads")


@app.on_event("startup")
def on_startup():
    Base.metadata.create_all(bind=engine)
    inspector = inspect(engine)
    columns_by_table = {table: {column["name"] for column in inspector.get_columns(table)} for table in inspector.get_table_names()}
    datetime_type = ddl_type(DateTime())
    with engine.begin() as conn:
        question_columns = columns_by_table.get("questions", set())
        if "questions" in columns_by_table and "section_id" not in question_columns:
            conn.execute(text("ALTER TABLE questions ADD COLUMN section_id INTEGER"))
        attempt_columns = columns_by_table.get("attempts", set())
        if "attempts" in columns_by_table and "max_score" not in attempt_columns:
            conn.execute(text("ALTER TABLE attempts ADD COLUMN max_score INTEGER DEFAULT 0"))
        if "attempts" in columns_by_table and "selected_question_ids_json" not in attempt_columns:
            conn.execute(text("ALTER TABLE attempts ADD COLUMN selected_question_ids_json TEXT"))
        if "attempts" in columns_by_table and "option_orders_json" not in attempt_columns:
            conn.execute(text("ALTER TABLE attempts ADD COLUMN option_orders_json TEXT"))
        if "attempts" in columns_by_table and "answers_json" not in attempt_columns:
            conn.execute(text("ALTER TABLE attempts ADD COLUMN answers_json TEXT"))
        test_config_columns = columns_by_table.get("test_configs", set())
        if "test_configs" in columns_by_table and "course_id" not in test_config_columns:
            conn.execute(text("ALTER TABLE test_configs ADD COLUMN course_id INTEGER"))
        if "test_configs" in columns_by_table and "created_by_id" not in test_config_columns:
            conn.execute(text("ALTER TABLE test_configs ADD COLUMN created_by_id INTEGER"))
        if "test_configs" in columns_by_table and "approval_status" not in test_config_columns:
            conn.execute(text("ALTER TABLE test_configs ADD COLUMN approval_status VARCHAR(20) DEFAULT 'approved'"))
        if "test_configs" in columns_by_table and "approved_by_id" not in test_config_columns:
            conn.execute(text("ALTER TABLE test_configs ADD COLUMN approved_by_id INTEGER"))
        if "test_configs" in columns_by_table and "approved_at" not in test_config_columns:
            conn.execute(text(f"ALTER TABLE test_configs ADD COLUMN approved_at {datetime_type}"))
        course_columns = columns_by_table.get("courses", set())
        if "courses" in columns_by_table and "created_by_id" not in course_columns:
            conn.execute(text("ALTER TABLE courses ADD COLUMN created_by_id INTEGER"))
        if "courses" in columns_by_table and "approval_status" not in course_columns:
            conn.execute(text("ALTER TABLE courses ADD COLUMN approval_status VARCHAR(20) DEFAULT 'approved'"))
        if "courses" in columns_by_table and "approved_by_id" not in course_columns:
            conn.execute(text("ALTER TABLE courses ADD COLUMN approved_by_id INTEGER"))
        if "courses" in columns_by_table and "approved_at" not in course_columns:
            conn.execute(text(f"ALTER TABLE courses ADD COLUMN approved_at {datetime_type}"))
        section_columns = columns_by_table.get("test_sections", set())
        if "test_sections" in columns_by_table and "order_index" not in section_columns:
            conn.execute(text("ALTER TABLE test_sections ADD COLUMN order_index INTEGER DEFAULT 0"))
        if "test_sections" in columns_by_table and "requires_full_score" not in section_columns:
            conn.execute(text("ALTER TABLE test_sections ADD COLUMN requires_full_score BOOLEAN DEFAULT FALSE"))
        if "test_sections" in columns_by_table and "section_type" not in section_columns:
            conn.execute(text("ALTER TABLE test_sections ADD COLUMN section_type VARCHAR(40) DEFAULT 'regular'"))
        if "test_sections" in columns_by_table and "global_question" not in section_columns:
            conn.execute(text("ALTER TABLE test_sections ADD COLUMN global_question TEXT"))


@app.get("/health")
def health():
    return {"ok": True}


@app.post("/auth/bootstrap-super-admin", response_model=UserOut)
def bootstrap_super_admin(payload: BootstrapSuperAdminIn, db: Annotated[Session, Depends(get_db)]):
    existing = db.scalar(select(User).where(User.role == UserRole.SUPER_ADMIN.value))
    if existing:
        raise HTTPException(status_code=409, detail="Super admin already exists.")

    same_username = db.scalar(select(User).where(User.username == payload.username.strip()))
    if same_username:
        raise HTTPException(status_code=409, detail="Username already exists.")

    same_email = db.scalar(select(User).where(User.email == payload.email))
    if same_email:
        raise HTTPException(status_code=409, detail="Email already exists.")

    user = User(
        username=payload.username.strip(),
        email=payload.email,
        password_hash=hash_password(payload.password),
        role=UserRole.SUPER_ADMIN.value,
        credits=0,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return serialize_user(user)


@app.post("/auth/login", response_model=TokenOut)
def login(form_data: Annotated[OAuth2PasswordRequestForm, Depends()], db: Annotated[Session, Depends(get_db)]):
    login_value = form_data.username.strip()
    user = db.scalar(select(User).where((User.username == login_value) | (User.email == login_value)))
    if user is None or not verify_password(form_data.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid username/email or password.")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="User account is inactive.")
    token = create_access_token(user)
    return TokenOut(access_token=token)


@app.get("/auth/me", response_model=UserOut)
def auth_me(current_user: Annotated[User, Depends(get_current_user)]):
    return serialize_user(current_user)


@app.get("/auth/moderator-invites/{token}", response_model=ModeratorInviteStatusOut)
def moderator_invite_status(token: str, db: Annotated[Session, Depends(get_db)]):
    try:
        invite = get_valid_moderator_invite(db, token)
    except HTTPException:
        return ModeratorInviteStatusOut(valid=False, expires_at=None)
    return ModeratorInviteStatusOut(valid=True, expires_at=invite.expires_at)


@app.post("/auth/moderator-invites/register", response_model=TokenOut)
def register_moderator_with_invite(payload: ModeratorInviteRegisterIn, db: Annotated[Session, Depends(get_db)]):
    invite = get_valid_moderator_invite(db, payload.token, lock=True)
    username = payload.username.strip()
    existing_username = db.scalar(select(User).where(User.username == username))
    if existing_username:
        raise HTTPException(status_code=409, detail="Username already exists.")
    existing_email = db.scalar(select(User).where(User.email == payload.email))
    if existing_email:
        raise HTTPException(status_code=409, detail="Email already exists.")

    user = User(
        username=username,
        email=payload.email,
        password_hash=hash_password(payload.password),
        role=UserRole.MODERATOR.value,
        credits=0,
        created_by_id=invite.created_by_id,
    )
    db.add(user)
    db.flush()
    invite.used_at = dt.datetime.utcnow()
    invite.moderator_user_id = user.id
    db.commit()
    db.refresh(user)
    return TokenOut(access_token=create_access_token(user))


@app.get("/admin/users", response_model=list[UserOut])
def admin_list_users(
    _: Annotated[User, Depends(require_roles(UserRole.ADMIN, UserRole.SUPER_ADMIN))],
    db: Annotated[Session, Depends(get_db)],
):
    users = db.scalars(select(User).order_by(User.id.asc())).all()
    return [serialize_user(user) for user in users]


@app.post("/admin/moderator-invites", response_model=ModeratorInviteOut)
def admin_create_moderator_invite(
    request: Request,
    current_user: Annotated[User, Depends(require_roles(UserRole.ADMIN, UserRole.SUPER_ADMIN))],
    db: Annotated[Session, Depends(get_db)],
):
    token = secrets.token_urlsafe(32)
    expires_at = dt.datetime.utcnow() + dt.timedelta(days=MODERATOR_INVITE_DAYS)
    invite = ModeratorInvite(
        token_hash=hash_invite_token(token),
        created_by_id=current_user.id,
        expires_at=expires_at,
    )
    db.add(invite)
    db.commit()
    db.refresh(invite)
    return ModeratorInviteOut(
        id=invite.id,
        token=token,
        registration_url=build_moderator_invite_url(request, token),
        expires_at=invite.expires_at,
        used_at=invite.used_at,
    )


@app.get("/admin/overview", response_model=AdminOverviewOut)
def admin_overview(
    current_user: Annotated[User, Depends(require_roles(UserRole.MODERATOR, UserRole.ADMIN, UserRole.SUPER_ADMIN))],
    db: Annotated[Session, Depends(get_db)],
):
    users = []
    if current_user.role in {UserRole.ADMIN.value, UserRole.SUPER_ADMIN.value}:
        users = db.scalars(select(User).order_by(User.id.asc())).all()
    configs = db.scalars(
        visible_content_query(current_user, TestConfig)
        .options(
            selectinload(TestConfig.questions),
            selectinload(TestConfig.sections).selectinload(TestSection.questions),
            selectinload(TestConfig.course),
            selectinload(TestConfig.author),
            selectinload(TestConfig.approver),
        )
        .order_by(TestConfig.topic_name, TestConfig.level_name)
    ).all()
    courses = db.scalars(
        visible_content_query(current_user, Course)
        .options(
            selectinload(Course.author),
            selectinload(Course.approver),
            selectinload(Course.modules),
            selectinload(Course.tests).selectinload(TestConfig.questions),
            selectinload(Course.tests).selectinload(TestConfig.sections).selectinload(TestSection.questions),
            selectinload(Course.tests).selectinload(TestConfig.course),
            selectinload(Course.tests).selectinload(TestConfig.author),
            selectinload(Course.tests).selectinload(TestConfig.approver),
        )
        .order_by(Course.title.asc(), Course.id.asc())
    ).all()
    sections_query = (
        select(TestSection)
        .join(TestConfig)
        .options(selectinload(TestSection.questions))
        .order_by(TestSection.test_config_id, TestSection.order_index, TestSection.id)
    )
    questions_query = select(Question).join(TestConfig).order_by(Question.id.desc())
    if current_user.role == UserRole.MODERATOR.value:
        sections_query = sections_query.where(TestConfig.created_by_id == current_user.id)
        questions_query = questions_query.where(TestConfig.created_by_id == current_user.id)
    sections = db.scalars(sections_query).all()
    questions = db.scalars(questions_query).all()
    return AdminOverviewOut(
        users=[serialize_user(user) for user in users],
        test_configs=[serialize_test_config(config) for config in configs],
        courses=[
            serialize_course(
                course,
                managed_by_user_id=current_user.id if current_user.role == UserRole.MODERATOR.value else None,
            )
            for course in courses
        ],
        sections=[serialize_test_section(section) for section in sections],
        questions=[serialize_question_admin(question) for question in questions],
    )


@app.get("/admin/users/{user_id}/stats", response_model=UserAdminStatsOut)
def admin_user_stats(
    user_id: int,
    current_user: Annotated[User, Depends(require_roles(UserRole.ADMIN, UserRole.SUPER_ADMIN))],
    db: Annotated[Session, Depends(get_db)],
):
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found.")
    if not can_manage_target_user(current_user, user):
        raise HTTPException(status_code=403, detail="You do not have permission to view this user.")
    return build_user_admin_stats(db, user)


@app.post("/admin/courses", response_model=CourseOut)
def admin_create_course(
    payload: CourseCreateIn,
    current_user: Annotated[User, Depends(require_roles(UserRole.MODERATOR, UserRole.ADMIN, UserRole.SUPER_ADMIN))],
    db: Annotated[Session, Depends(get_db)],
):
    title = payload.title.strip()
    duplicate = db.scalar(select(Course).where(func.lower(Course.title) == title.lower()))
    if duplicate is not None:
        raise HTTPException(status_code=409, detail="A course with this title already exists.")
    course = Course(
        title=title,
        summary=payload.summary.strip(),
        content=payload.content.strip(),
        is_active=payload.is_active,
        created_by_id=current_user.id,
        **approval_fields_for_create(current_user),
    )
    db.add(course)
    db.commit()
    db.refresh(course)
    return serialize_course(course)


@app.patch("/admin/courses/{course_id}", response_model=CourseOut)
def admin_update_course(
    course_id: int,
    payload: CourseUpdateIn,
    current_user: Annotated[User, Depends(require_roles(UserRole.MODERATOR, UserRole.ADMIN, UserRole.SUPER_ADMIN))],
    db: Annotated[Session, Depends(get_db)],
):
    course = db.get(Course, course_id)
    if course is None:
        raise HTTPException(status_code=404, detail="Course not found.")
    require_content_access(current_user, course, "courses")
    if payload.title is not None:
        title = payload.title.strip()
        duplicate = db.scalar(select(Course).where(func.lower(Course.title) == title.lower(), Course.id != course.id))
        if duplicate is not None:
            raise HTTPException(status_code=409, detail="A course with this title already exists.")
        course.title = title
    if payload.summary is not None:
        course.summary = payload.summary.strip()
    if payload.content is not None:
        course.content = payload.content.strip()
    if payload.is_active is not None:
        course.is_active = payload.is_active
    mark_pending_after_moderator_edit(current_user, course)
    db.commit()
    db.refresh(course)
    return serialize_course(course)


@app.post("/admin/course-modules", response_model=CourseModuleOut)
def admin_create_course_module(
    payload: CourseModuleCreateIn,
    current_user: Annotated[User, Depends(require_roles(UserRole.MODERATOR, UserRole.ADMIN, UserRole.SUPER_ADMIN))],
    db: Annotated[Session, Depends(get_db)],
):
    course = db.get(Course, payload.course_id)
    if course is None:
        raise HTTPException(status_code=404, detail="Course not found.")
    require_content_access(current_user, course, "courses")
    next_order = (
        db.scalar(select(func.max(CourseModule.order_index)).where(CourseModule.course_id == course.id))
        or 0
    ) + 1
    module = CourseModule(
        course_id=course.id,
        title=payload.title.strip(),
        module_type=normalize_module_type(payload.module_type),
        content=payload.content.strip(),
        resource_url=payload.resource_url.strip(),
        order_index=payload.order_index if payload.order_index is not None else next_order,
        is_active=payload.is_active,
    )
    mark_pending_after_moderator_edit(current_user, course)
    db.add(module)
    db.commit()
    db.refresh(module)
    return serialize_course_module(module)


@app.patch("/admin/course-modules/{module_id}", response_model=CourseModuleOut)
def admin_update_course_module(
    module_id: int,
    payload: CourseModuleUpdateIn,
    current_user: Annotated[User, Depends(require_roles(UserRole.MODERATOR, UserRole.ADMIN, UserRole.SUPER_ADMIN))],
    db: Annotated[Session, Depends(get_db)],
):
    module = db.get(CourseModule, module_id)
    if module is None:
        raise HTTPException(status_code=404, detail="Module not found.")
    require_content_access(current_user, module.course, "courses")
    if payload.title is not None:
        module.title = payload.title.strip()
    if payload.module_type is not None:
        module.module_type = normalize_module_type(payload.module_type)
    if payload.content is not None:
        module.content = payload.content.strip()
    if payload.resource_url is not None:
        module.resource_url = payload.resource_url.strip()
    if payload.order_index is not None:
        module.order_index = payload.order_index
    if payload.is_active is not None:
        module.is_active = payload.is_active
    mark_pending_after_moderator_edit(current_user, module.course)
    db.commit()
    db.refresh(module)
    return serialize_course_module(module)


@app.delete("/admin/course-modules/{module_id}")
def admin_delete_course_module(
    module_id: int,
    current_user: Annotated[User, Depends(require_roles(UserRole.MODERATOR, UserRole.ADMIN, UserRole.SUPER_ADMIN))],
    db: Annotated[Session, Depends(get_db)],
):
    module = db.get(CourseModule, module_id)
    if module is None:
        raise HTTPException(status_code=404, detail="Module not found.")
    require_content_access(current_user, module.course, "courses")
    mark_pending_after_moderator_edit(current_user, module.course)
    db.delete(module)
    db.commit()
    return {"deleted": True}


@app.post("/admin/course-module-files", response_model=CourseModuleFileOut)
def admin_upload_course_module_file(
    _: Annotated[User, Depends(require_roles(UserRole.MODERATOR, UserRole.ADMIN, UserRole.SUPER_ADMIN))],
    file: UploadFile = File(...),
):
    original = Path(file.filename or "course-file").name
    suffix = Path(original).suffix.lower()
    allowed = {".pdf", ".doc", ".docx", ".ppt", ".pptx", ".mp4", ".webm", ".mov", ".m4v"}
    if suffix not in allowed:
        raise HTTPException(status_code=400, detail="Unsupported file type.")
    stored_name = f"{secrets.token_urlsafe(16)}{suffix}"
    target = COURSE_UPLOAD_DIR / stored_name
    with target.open("wb") as handle:
        shutil.copyfileobj(file.file, handle)
    return CourseModuleFileOut(url=f"/uploads/course_modules/{stored_name}", filename=original)


@app.delete("/admin/courses/{course_id}")
def admin_delete_course(
    course_id: int,
    current_user: Annotated[User, Depends(require_roles(UserRole.MODERATOR, UserRole.ADMIN, UserRole.SUPER_ADMIN))],
    db: Annotated[Session, Depends(get_db)],
):
    course = db.get(Course, course_id)
    if course is None:
        raise HTTPException(status_code=404, detail="Course not found.")
    require_content_access(current_user, course, "courses")
    for config in course.tests:
        config.course_id = None
    db.execute(delete(CourseCompletion).where(CourseCompletion.course_id == course_id))
    db.delete(course)
    db.commit()
    return {"deleted": True}


@app.patch("/admin/courses/{course_id}/approval", response_model=CourseOut)
def admin_set_course_approval(
    course_id: int,
    payload: ContentApprovalIn,
    current_user: Annotated[User, Depends(require_roles(UserRole.ADMIN, UserRole.SUPER_ADMIN))],
    db: Annotated[Session, Depends(get_db)],
):
    course = db.get(Course, course_id)
    if course is None:
        raise HTTPException(status_code=404, detail="Course not found.")
    if payload.approved:
        course.approval_status = "approved"
        course.approved_by_id = current_user.id
        course.approved_at = dt.datetime.utcnow()
    else:
        course.approval_status = "rejected"
        course.approved_by_id = current_user.id
        course.approved_at = dt.datetime.utcnow()
    db.commit()
    db.refresh(course)
    return serialize_course(course)


@app.post("/admin/test-access-overrides")
def admin_set_test_access_override(
    payload: TestAccessOverrideIn,
    current_user: Annotated[User, Depends(require_roles(UserRole.ADMIN, UserRole.SUPER_ADMIN))],
    db: Annotated[Session, Depends(get_db)],
):
    user = db.get(User, payload.user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found.")
    if not can_manage_target_user(current_user, user):
        raise HTTPException(status_code=403, detail="You do not have permission to modify this user.")
    config = db.get(TestConfig, payload.test_config_id)
    if config is None:
        raise HTTPException(status_code=404, detail="Test config not found.")
    existing = db.get(TestAccessOverride, {"user_id": user.id, "test_config_id": config.id})
    if payload.grant:
        if existing is None:
            db.add(TestAccessOverride(user_id=user.id, test_config_id=config.id))
    elif existing is not None:
        db.delete(existing)
    db.commit()
    return {"ok": True, "granted": payload.grant}


@app.post("/admin/users", response_model=UserOut)
def admin_create_user(
    payload: UserCreateIn,
    current_user: Annotated[User, Depends(require_roles(UserRole.ADMIN, UserRole.SUPER_ADMIN))],
    db: Annotated[Session, Depends(get_db)],
):
    if payload.role == UserRole.SUPER_ADMIN:
        raise HTTPException(status_code=403, detail="Cannot create another super admin through this endpoint.")
    if current_user.role == UserRole.ADMIN.value and payload.role not in {UserRole.USER, UserRole.MODERATOR}:
        raise HTTPException(status_code=403, detail="Admins can only create users and moderators.")

    existing_username = db.scalar(select(User).where(User.username == payload.username.strip()))
    if existing_username:
        raise HTTPException(status_code=409, detail="Username already exists.")
    existing_email = db.scalar(select(User).where(User.email == payload.email))
    if existing_email:
        raise HTTPException(status_code=409, detail="Email already exists.")

    user = User(
        username=payload.username.strip(),
        email=payload.email,
        password_hash=hash_password(payload.password),
        role=payload.role.value,
        credits=payload.credits,
        created_by_id=current_user.id,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return serialize_user(user)


@app.patch("/admin/users/{user_id}", response_model=UserOut)
def admin_update_user(
    user_id: int,
    payload: UserAdminUpdateIn,
    current_user: Annotated[User, Depends(require_roles(UserRole.ADMIN, UserRole.SUPER_ADMIN))],
    db: Annotated[Session, Depends(get_db)],
):
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found.")
    if not can_manage_target_user(current_user, user):
        raise HTTPException(status_code=403, detail="You do not have permission to modify this user.")

    if payload.role == UserRole.SUPER_ADMIN:
        raise HTTPException(status_code=403, detail="Cannot assign super admin role.")
    if user.role == UserRole.SUPER_ADMIN.value and payload.role is not None and payload.role.value != user.role:
        raise HTTPException(status_code=403, detail="Super admin role cannot be changed.")
    if current_user.role == UserRole.ADMIN.value and payload.role is not None and payload.role not in {UserRole.USER, UserRole.MODERATOR}:
        raise HTTPException(status_code=403, detail="Admins can only assign user or moderator role.")

    if payload.username is not None:
        username_clean = payload.username.strip()
        same_username = db.scalar(select(User).where(User.username == username_clean, User.id != user.id))
        if same_username:
            raise HTTPException(status_code=409, detail="Username already exists.")
        user.username = username_clean
    if payload.email is not None:
        same_email = db.scalar(select(User).where(User.email == payload.email, User.id != user.id))
        if same_email:
            raise HTTPException(status_code=409, detail="Email already exists.")
        user.email = payload.email
    if payload.role is not None:
        user.role = payload.role.value
    if payload.credits is not None:
        user.credits = payload.credits
    if payload.is_active is not None:
        user.is_active = payload.is_active
    if payload.password is not None and payload.password.strip():
        user.password_hash = hash_password(payload.password)

    db.commit()
    db.refresh(user)
    return serialize_user(user)


@app.patch("/admin/users/{user_id}/credits", response_model=UserOut)
def admin_add_user_credits(
    user_id: int,
    payload: CreditUpdateIn,
    current_user: Annotated[User, Depends(require_roles(UserRole.ADMIN, UserRole.SUPER_ADMIN))],
    db: Annotated[Session, Depends(get_db)],
):
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found.")
    if not can_manage_target_user(current_user, user):
        raise HTTPException(status_code=403, detail="You do not have permission to modify this user.")
    user.credits += payload.credits_to_add
    db.commit()
    db.refresh(user)
    return serialize_user(user)


@app.delete("/admin/users/{user_id}")
def admin_delete_user(
    user_id: int,
    current_user: Annotated[User, Depends(require_roles(UserRole.ADMIN, UserRole.SUPER_ADMIN))],
    db: Annotated[Session, Depends(get_db)],
):
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found.")
    if user.id == current_user.id:
        raise HTTPException(status_code=400, detail="You cannot delete your own account.")
    if not can_manage_target_user(current_user, user):
        raise HTTPException(status_code=403, detail="You do not have permission to delete this user.")

    created_users = db.scalars(select(User).where(User.created_by_id == user.id)).all()
    for created_user in created_users:
        created_user.created_by_id = None
    authored_tests = db.scalars(select(TestConfig).where(TestConfig.created_by_id == user.id)).all()
    for test_config in authored_tests:
        test_config.created_by_id = None
    authored_courses = db.scalars(select(Course).where(Course.created_by_id == user.id)).all()
    for course in authored_courses:
        course.created_by_id = None

    db.execute(
        delete(UserFollow).where(
            (UserFollow.follower_id == user.id) | (UserFollow.following_id == user.id),
        )
    )
    db.execute(delete(TestComment).where(TestComment.user_id == user.id))
    db.execute(delete(CourseCompletion).where(CourseCompletion.user_id == user.id))
    db.execute(delete(TestAccessOverride).where(TestAccessOverride.user_id == user.id))
    db.execute(delete(Attempt).where(Attempt.user_id == user.id))
    db.delete(user)
    db.commit()
    return {"deleted": True}


@app.post("/admin/test-configs", response_model=TestConfigOut)
def admin_upsert_test_config(
    payload: TestConfigCreateIn,
    current_user: Annotated[User, Depends(require_roles(UserRole.MODERATOR, UserRole.ADMIN, UserRole.SUPER_ADMIN))],
    db: Annotated[Session, Depends(get_db)],
):
    existing = db.scalar(
        select(TestConfig).where(
            TestConfig.topic_name == payload.topic_name.strip(),
            TestConfig.level_name == payload.level_name.strip(),
        )
    )
    if payload.course_id is not None:
        course = db.get(Course, payload.course_id)
        if course is None:
            raise HTTPException(status_code=404, detail="Course not found.")
        require_content_access(current_user, course, "courses")
    if existing:
        require_content_access(current_user, existing, "tests")
        existing.duration_seconds = payload.duration_seconds
        existing.passing_percent = payload.passing_percent
        existing.is_active = payload.is_active
        existing.course_id = payload.course_id
        mark_pending_after_moderator_edit(current_user, existing)
        db.commit()
        db.refresh(existing)
        return serialize_test_config(existing)

    config = TestConfig(
        topic_name=payload.topic_name.strip(),
        level_name=payload.level_name.strip(),
        duration_seconds=payload.duration_seconds,
        passing_percent=payload.passing_percent,
        is_active=payload.is_active,
        course_id=payload.course_id,
        created_by_id=current_user.id,
        **approval_fields_for_create(current_user),
    )
    db.add(config)
    db.commit()
    db.refresh(config)
    return serialize_test_config(config)


@app.get("/admin/test-configs", response_model=list[TestConfigOut])
def admin_list_test_configs(
    current_user: Annotated[User, Depends(require_roles(UserRole.MODERATOR, UserRole.ADMIN, UserRole.SUPER_ADMIN))],
    db: Annotated[Session, Depends(get_db)],
):
    configs = db.scalars(
        visible_content_query(current_user, TestConfig)
        .options(
            selectinload(TestConfig.questions),
            selectinload(TestConfig.sections).selectinload(TestSection.questions),
            selectinload(TestConfig.course),
            selectinload(TestConfig.author),
            selectinload(TestConfig.approver),
        )
        .order_by(TestConfig.topic_name, TestConfig.level_name)
    ).all()
    return [serialize_test_config(config) for config in configs]


@app.patch("/admin/test-configs/{test_config_id}", response_model=TestConfigOut)
def admin_update_test_config(
    test_config_id: int,
    payload: TestConfigUpdateIn,
    current_user: Annotated[User, Depends(require_roles(UserRole.MODERATOR, UserRole.ADMIN, UserRole.SUPER_ADMIN))],
    db: Annotated[Session, Depends(get_db)],
):
    config = db.get(TestConfig, test_config_id)
    if config is None:
        raise HTTPException(status_code=404, detail="Test config not found.")
    require_content_access(current_user, config, "tests")

    if payload.topic_name is not None:
        config.topic_name = payload.topic_name.strip()
    if payload.level_name is not None:
        config.level_name = payload.level_name.strip()
    if payload.duration_seconds is not None:
        config.duration_seconds = payload.duration_seconds
    if payload.passing_percent is not None:
        config.passing_percent = payload.passing_percent
    if payload.is_active is not None:
        config.is_active = payload.is_active
    if "course_id" in payload.model_fields_set:
        if payload.course_id is not None:
            course = db.get(Course, payload.course_id)
            if course is None:
                raise HTTPException(status_code=404, detail="Course not found.")
            require_content_access(current_user, course, "courses")
        config.course_id = payload.course_id
    mark_pending_after_moderator_edit(current_user, config)

    db.commit()
    db.refresh(config)
    return serialize_test_config(config)


@app.delete("/admin/test-configs/{test_config_id}")
def admin_delete_test_config(
    test_config_id: int,
    current_user: Annotated[User, Depends(require_roles(UserRole.MODERATOR, UserRole.ADMIN, UserRole.SUPER_ADMIN))],
    db: Annotated[Session, Depends(get_db)],
):
    config = db.get(TestConfig, test_config_id)
    if config is None:
        raise HTTPException(status_code=404, detail="Test config not found.")
    require_content_access(current_user, config, "tests")

    attempt_count = db.scalar(select(func.count(Attempt.id)).where(Attempt.test_config_id == test_config_id)) or 0
    if int(attempt_count) > 0:
        raise HTTPException(
            status_code=409,
            detail="Cannot delete a test config that already has attempts.",
        )

    db.execute(delete(TestComment).where(TestComment.test_config_id == test_config_id))
    db.execute(delete(TestAccessOverride).where(TestAccessOverride.test_config_id == test_config_id))
    db.delete(config)
    db.commit()
    return {"deleted": True}


@app.patch("/admin/test-configs/{test_config_id}/approval", response_model=TestConfigOut)
def admin_set_test_config_approval(
    test_config_id: int,
    payload: ContentApprovalIn,
    current_user: Annotated[User, Depends(require_roles(UserRole.ADMIN, UserRole.SUPER_ADMIN))],
    db: Annotated[Session, Depends(get_db)],
):
    config = db.get(TestConfig, test_config_id)
    if config is None:
        raise HTTPException(status_code=404, detail="Test config not found.")
    if payload.approved:
        config.approval_status = "approved"
        config.approved_by_id = current_user.id
        config.approved_at = dt.datetime.utcnow()
    else:
        config.approval_status = "rejected"
        config.approved_by_id = current_user.id
        config.approved_at = dt.datetime.utcnow()
    db.commit()
    db.refresh(config)
    return serialize_test_config(config)


@app.post("/admin/test-sections", response_model=TestSectionOut)
def admin_create_test_section(
    payload: TestSectionCreateIn,
    current_user: Annotated[User, Depends(require_roles(UserRole.MODERATOR, UserRole.ADMIN, UserRole.SUPER_ADMIN))],
    db: Annotated[Session, Depends(get_db)],
):
    config = db.get(TestConfig, payload.test_config_id)
    if config is None:
        raise HTTPException(status_code=404, detail="Test config not found.")
    require_content_access(current_user, config, "tests")
    name = payload.name.strip()
    duplicate = db.scalar(
        select(TestSection).where(
            TestSection.test_config_id == payload.test_config_id,
            func.lower(TestSection.name) == name.lower(),
        )
    )
    if duplicate is not None:
        raise HTTPException(status_code=409, detail="A section with this name already exists for this test.")
    section_type = section_type_from_payload(payload.section_type, payload.global_question)
    global_question = normalize_global_question(section_type, payload.global_question)
    if section_type == "case_scenario" and not global_question:
        raise HTTPException(status_code=400, detail="Global question is required for case-scenario sections.")
    next_order = (
        db.scalar(
            select(func.max(TestSection.order_index)).where(TestSection.test_config_id == payload.test_config_id)
        )
        or 0
    ) + 1
    section = TestSection(
        test_config_id=payload.test_config_id,
        name=name,
        select_count=payload.select_count,
        points_per_question=payload.points_per_question,
        order_index=next_order,
        requires_full_score=payload.requires_full_score,
        section_type=section_type,
        global_question=global_question,
    )
    mark_pending_after_moderator_edit(current_user, config)
    db.add(section)
    db.commit()
    db.refresh(section)
    return serialize_test_section(section)


@app.get("/admin/test-sections", response_model=list[TestSectionOut])
def admin_list_test_sections(
    current_user: Annotated[User, Depends(require_roles(UserRole.MODERATOR, UserRole.ADMIN, UserRole.SUPER_ADMIN))],
    db: Annotated[Session, Depends(get_db)],
    test_config_id: int | None = Query(default=None),
):
    query = select(TestSection).join(TestConfig).options(selectinload(TestSection.questions)).order_by(
        TestSection.test_config_id,
        TestSection.order_index,
        TestSection.id,
    )
    if current_user.role == UserRole.MODERATOR.value:
        query = query.where(TestConfig.created_by_id == current_user.id)
    if test_config_id is not None:
        query = query.where(TestSection.test_config_id == test_config_id)
    sections = db.scalars(query).all()
    return [serialize_test_section(section) for section in sections]


@app.patch("/admin/test-configs/{test_config_id}/sections/reorder", response_model=list[TestSectionOut])
def admin_reorder_test_sections(
    test_config_id: int,
    payload: TestSectionReorderIn,
    current_user: Annotated[User, Depends(require_roles(UserRole.MODERATOR, UserRole.ADMIN, UserRole.SUPER_ADMIN))],
    db: Annotated[Session, Depends(get_db)],
):
    config = db.get(TestConfig, test_config_id)
    if config is None:
        raise HTTPException(status_code=404, detail="Test config not found.")
    require_content_access(current_user, config, "tests")
    sections = db.scalars(
        select(TestSection)
        .options(selectinload(TestSection.questions))
        .where(TestSection.test_config_id == test_config_id)
        .order_by(TestSection.order_index, TestSection.id)
    ).all()
    section_by_id = {section.id: section for section in sections}
    ordered_ids = []
    for item in payload.section_ids:
        section_id = int(item)
        if section_id not in section_by_id:
            raise HTTPException(status_code=400, detail="Section order contains an invalid section.")
        if section_id not in ordered_ids:
            ordered_ids.append(section_id)
    ordered_ids.extend(section.id for section in sections if section.id not in ordered_ids)
    for index, section_id in enumerate(ordered_ids, start=1):
        section_by_id[section_id].order_index = index
    mark_pending_after_moderator_edit(current_user, config)
    db.commit()
    reordered = sorted(sections, key=lambda item: (item.order_index, item.id))
    return [serialize_test_section(section) for section in reordered]


@app.patch("/admin/test-sections/{section_id}", response_model=TestSectionOut)
def admin_update_test_section(
    section_id: int,
    payload: TestSectionUpdateIn,
    current_user: Annotated[User, Depends(require_roles(UserRole.MODERATOR, UserRole.ADMIN, UserRole.SUPER_ADMIN))],
    db: Annotated[Session, Depends(get_db)],
):
    section = db.get(TestSection, section_id)
    if section is None:
        raise HTTPException(status_code=404, detail="Section not found.")
    require_content_access(current_user, section.test_config, "tests")
    if payload.name is not None:
        name = payload.name.strip()
        duplicate = db.scalar(
            select(TestSection).where(
                TestSection.test_config_id == section.test_config_id,
                func.lower(TestSection.name) == name.lower(),
                TestSection.id != section.id,
            )
        )
        if duplicate is not None:
            raise HTTPException(status_code=409, detail="A section with this name already exists for this test.")
        section.name = name
    if payload.select_count is not None:
        section.select_count = payload.select_count
    if payload.points_per_question is not None:
        section.points_per_question = payload.points_per_question
    if payload.requires_full_score is not None:
        section.requires_full_score = payload.requires_full_score
    section_type = normalize_section_type(section.section_type)
    if payload.section_type is not None:
        section_type = section_type_from_payload(payload.section_type, payload.global_question)
        section.section_type = section_type
    if "global_question" in payload.model_fields_set or payload.section_type is not None:
        section.global_question = normalize_global_question(section_type, payload.global_question)
    if section.section_type == "case_scenario" and not section.global_question:
        raise HTTPException(status_code=400, detail="Global question is required for case-scenario sections.")
    mark_pending_after_moderator_edit(current_user, section.test_config)
    db.commit()
    db.refresh(section)
    return serialize_test_section(section)


@app.delete("/admin/test-sections/{section_id}")
def admin_delete_test_section(
    section_id: int,
    current_user: Annotated[User, Depends(require_roles(UserRole.MODERATOR, UserRole.ADMIN, UserRole.SUPER_ADMIN))],
    db: Annotated[Session, Depends(get_db)],
):
    section = db.get(TestSection, section_id)
    if section is None:
        raise HTTPException(status_code=404, detail="Section not found.")
    require_content_access(current_user, section.test_config, "tests")
    mark_pending_after_moderator_edit(current_user, section.test_config)
    for question in section.questions:
        question.section_id = None
    db.delete(section)
    db.commit()
    return {"deleted": True}


@app.post("/admin/questions", response_model=QuestionPublicOut)
def admin_add_question(
    payload: QuestionCreateIn,
    current_user: Annotated[User, Depends(require_roles(UserRole.MODERATOR, UserRole.ADMIN, UserRole.SUPER_ADMIN))],
    db: Annotated[Session, Depends(get_db)],
):
    config = db.get(TestConfig, payload.test_config_id)
    if config is None:
        raise HTTPException(status_code=404, detail="Test config not found.")
    require_content_access(current_user, config, "tests")
    if payload.section_id is not None:
        section = db.get(TestSection, payload.section_id)
        if section is None or section.test_config_id != payload.test_config_id:
            raise HTTPException(status_code=400, detail="Selected section does not belong to this test.")
    cleaned_options = [item.strip() for item in payload.options]
    if any(not item for item in cleaned_options):
        raise HTTPException(status_code=400, detail="All options are required.")
    if len(set(item.lower() for item in cleaned_options)) != len(cleaned_options):
        raise HTTPException(status_code=400, detail="Question options must be unique.")
    clean_correct_indices = sorted({int(item) for item in payload.correct_indices if int(item) >= 0})
    if not clean_correct_indices:
        raise HTTPException(status_code=400, detail="At least one correct answer must be selected.")
    if any(item >= len(cleaned_options) for item in clean_correct_indices):
        raise HTTPException(status_code=400, detail="Correct answer index is out of bounds.")

    question = Question(
        test_config_id=payload.test_config_id,
        section_id=payload.section_id,
        question_text=payload.question_text.strip(),
        options_json=build_question_payload(cleaned_options, clean_correct_indices),
        correct_index=clean_correct_indices[0],
    )
    mark_pending_after_moderator_edit(current_user, config)
    db.add(question)
    db.commit()
    db.refresh(question)
    return QuestionPublicOut(
        id=question.id,
        section_id=question.section_id,
        section_name=question.section.name if question.section is not None else None,
        section_type=(question.section.section_type or "regular") if question.section is not None else "regular",
        global_question=question.section.global_question if question.section is not None else None,
        question_text=question.question_text,
        options=cleaned_options,
    )


@app.get("/admin/questions", response_model=list[QuestionAdminOut])
def admin_list_questions(
    current_user: Annotated[User, Depends(require_roles(UserRole.MODERATOR, UserRole.ADMIN, UserRole.SUPER_ADMIN))],
    db: Annotated[Session, Depends(get_db)],
    test_config_id: int | None = Query(default=None),
):
    query = select(Question).join(TestConfig).order_by(Question.id.desc())
    if current_user.role == UserRole.MODERATOR.value:
        query = query.where(TestConfig.created_by_id == current_user.id)
    if test_config_id is not None:
        query = query.where(Question.test_config_id == test_config_id)
    questions = db.scalars(query).all()
    return [serialize_question_admin(item) for item in questions]


@app.patch("/admin/questions/{question_id}", response_model=QuestionAdminOut)
def admin_update_question(
    question_id: int,
    payload: QuestionUpdateIn,
    current_user: Annotated[User, Depends(require_roles(UserRole.MODERATOR, UserRole.ADMIN, UserRole.SUPER_ADMIN))],
    db: Annotated[Session, Depends(get_db)],
):
    question = db.get(Question, question_id)
    if question is None:
        raise HTTPException(status_code=404, detail="Question not found.")
    require_content_access(current_user, question.test_config, "tests")

    if "section_id" in payload.model_fields_set:
        if payload.section_id is None:
            question.section_id = None
        else:
            section = db.get(TestSection, payload.section_id)
            if section is None or section.test_config_id != question.test_config_id:
                raise HTTPException(status_code=400, detail="Selected section does not belong to this test.")
            question.section_id = payload.section_id

    if payload.question_text is not None:
        question.question_text = payload.question_text.strip()

    options, correct_indices = parse_question_payload(question.options_json, question.correct_index)
    if payload.options is not None:
        cleaned_options = [item.strip() for item in payload.options]
        if any(not item for item in cleaned_options):
            raise HTTPException(status_code=400, detail="All options are required.")
        if len(set(item.lower() for item in cleaned_options)) != len(cleaned_options):
            raise HTTPException(status_code=400, detail="Question options must be unique.")
        options = cleaned_options
        correct_indices = [item for item in correct_indices if item < len(options)]

    if payload.correct_indices is not None:
        candidate_indices = sorted({int(item) for item in payload.correct_indices if int(item) >= 0})
        if not candidate_indices:
            raise HTTPException(status_code=400, detail="At least one correct answer must be selected.")
        if any(item >= len(options) for item in candidate_indices):
            raise HTTPException(status_code=400, detail="Correct answer index is out of bounds for provided options.")
        correct_indices = candidate_indices
    elif not correct_indices:
        raise HTTPException(status_code=400, detail="At least one correct answer must be selected.")

    question.correct_index = correct_indices[0]
    question.options_json = build_question_payload(options, correct_indices)
    mark_pending_after_moderator_edit(current_user, question.test_config)

    db.commit()
    db.refresh(question)
    return serialize_question_admin(question)


@app.delete("/admin/questions/{question_id}")
def admin_delete_question(
    question_id: int,
    current_user: Annotated[User, Depends(require_roles(UserRole.MODERATOR, UserRole.ADMIN, UserRole.SUPER_ADMIN))],
    db: Annotated[Session, Depends(get_db)],
):
    question = db.get(Question, question_id)
    if question is None:
        raise HTTPException(status_code=404, detail="Question not found.")
    require_content_access(current_user, question.test_config, "tests")
    mark_pending_after_moderator_edit(current_user, question.test_config)
    db.delete(question)
    db.commit()
    return {"deleted": True}


@app.post("/courses/{course_id}/modules/{module_id}/open", response_model=CourseOut)
def open_course_module(
    course_id: int,
    module_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    course = db.get(Course, course_id)
    if course is None or not is_content_published(course):
        raise HTTPException(status_code=404, detail="Course not found.")
    module = db.get(CourseModule, module_id)
    if module is None or module.course_id != course.id or not module.is_active:
        raise HTTPException(status_code=404, detail="Module not found.")
    active_modules = sorted(
        [item for item in course.modules if item.is_active],
        key=lambda item: (item.order_index, item.id),
    )
    if active_modules and active_modules[-1].id == module.id and db.get(
        CourseCompletion,
        {"user_id": current_user.id, "course_id": course.id},
    ) is None:
        db.add(CourseCompletion(user_id=current_user.id, course_id=course.id))
        db.commit()
        db.refresh(course)
    completed_course_ids = user_completed_course_ids(db, current_user.id)
    override_test_ids = user_override_test_ids(db, current_user.id)
    return serialize_course(
        course,
        completed_course_ids=completed_course_ids,
        override_test_ids=override_test_ids,
        public_only=True,
    )


@app.get("/tests/catalog", response_model=list[TestConfigOut])
def user_list_test_catalog(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    completed_course_ids = user_completed_course_ids(db, current_user.id)
    override_test_ids = user_override_test_ids(db, current_user.id)
    configs = db.scalars(
        select(TestConfig)
        .options(
            selectinload(TestConfig.questions),
            selectinload(TestConfig.sections).selectinload(TestSection.questions),
            selectinload(TestConfig.course),
            selectinload(TestConfig.author),
            selectinload(TestConfig.approver),
        )
        .where(TestConfig.is_active.is_(True), TestConfig.approval_status == "approved")
        .order_by(TestConfig.topic_name, TestConfig.level_name)
    ).all()
    return [
        serialize_test_config(config, completed_course_ids=completed_course_ids, override_test_ids=override_test_ids)
        for config in configs
        if config.course_id is None or (config.course is not None and is_content_published(config.course))
    ]


@app.post("/tests/start/{test_config_id}", response_model=TestStartOut)
def user_start_test(
    test_config_id: int,
    current_user: Annotated[User, Depends(require_roles(UserRole.USER, UserRole.MODERATOR, UserRole.ADMIN, UserRole.SUPER_ADMIN))],
    db: Annotated[Session, Depends(get_db)],
):
    config = db.get(TestConfig, test_config_id)
    if config is None or not is_content_published(config):
        raise HTTPException(status_code=404, detail="Test config not found, inactive, or pending approval.")
    if config.course_id is not None:
        if config.course is None or not is_content_published(config.course):
            raise HTTPException(status_code=403, detail="The linked course is not available yet.")
        completed = db.get(CourseCompletion, {"user_id": current_user.id, "course_id": config.course_id}) is not None
        override = db.get(TestAccessOverride, {"user_id": current_user.id, "test_config_id": config.id}) is not None
        if not completed and not override:
            raise HTTPException(status_code=403, detail="Finish the linked course before starting this test.")
    if current_user.credits < 1:
        raise HTTPException(status_code=402, detail="Insufficient credits. 1 credit is required per test try.")
    if len(config.questions) == 0:
        raise HTTPException(status_code=400, detail="This test has no questions yet.")

    randomizer = secrets.SystemRandom()
    if config.sections:
        selected_questions: list[Question] = []
        ordered_sections = sorted(config.sections, key=lambda item: (item.order_index, item.id))
        for section in ordered_sections:
            section_questions = list(section.questions)
            randomizer.shuffle(section_questions)
            selected_questions.extend(section_questions[: section.select_count])
        if not selected_questions:
            raise HTTPException(status_code=400, detail="This test has no selectable section questions yet.")
    else:
        selected_questions = list(config.questions)
        randomizer.shuffle(selected_questions)
    selected_question_ids = [question.id for question in selected_questions]
    max_score = sum(question_points(question) for question in selected_questions)
    question_payloads = []
    option_orders: dict[str, list[int]] = {}
    for question in selected_questions:
        options, correct_indices = parse_question_payload(question.options_json, question.correct_index)
        order = shuffled_option_order(len(options), randomizer)
        option_orders[str(question.id)] = order
        question_payloads.append(
            QuestionPublicOut(
                id=question.id,
                section_id=question.section_id,
                section_name=question.section.name if question.section is not None else None,
                section_type=(question.section.section_type or "regular") if question.section is not None else "regular",
                global_question=question.section.global_question if question.section is not None else None,
                question_text=question.question_text,
                options=[options[index] for index in order],
                allow_multiple=len(correct_indices) > 1,
            )
        )

    current_user.credits -= 1
    attempt = Attempt(
        user_id=current_user.id,
        test_config_id=config.id,
        status=AttemptStatus.IN_PROGRESS.value,
        total_questions=len(selected_questions),
        max_score=max_score,
        selected_question_ids_json=json.dumps(selected_question_ids),
        option_orders_json=json.dumps(option_orders),
    )
    db.add(attempt)
    db.commit()
    db.refresh(attempt)

    return TestStartOut(
        attempt_id=attempt.id,
        duration_seconds=config.duration_seconds,
        passing_percent=config.passing_percent,
        remaining_credits=current_user.credits,
        questions=question_payloads,
    )


@app.post("/tests/submit/{attempt_id}", response_model=SubmitAttemptOut)
def user_submit_test(
    attempt_id: int,
    payload: SubmitAttemptIn,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    attempt = db.get(Attempt, attempt_id)
    if attempt is None or attempt.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Attempt not found.")
    if attempt.status != AttemptStatus.IN_PROGRESS.value:
        raise HTTPException(status_code=400, detail="Attempt is already finalized.")

    config = db.get(TestConfig, attempt.test_config_id)
    if config is None:
        raise HTTPException(status_code=404, detail="Test config not found.")

    selected_ids = parse_selected_question_ids(attempt.selected_question_ids_json)
    if selected_ids:
        question_by_id = {question.id: question for question in config.questions}
        questions = [question_by_id[question_id] for question_id in selected_ids if question_id in question_by_id]
    else:
        questions = list(config.questions)
    if not questions:
        raise HTTPException(status_code=400, detail="No questions configured for this test.")

    score = 0
    total_questions = len(questions)
    max_score = sum(question_points(question) for question in questions)
    answer_map = payload.answers
    option_orders = parse_option_orders(attempt.option_orders_json)
    scored_by_section: dict[int | None, dict[str, int]] = {}

    for question in questions:
        _, correct_indices = parse_question_payload(question.options_json, question.correct_index)
        option_order = option_orders.get(question.id)
        selected_raw = answer_map.get(question.id, answer_map.get(str(question.id), -1))
        if isinstance(selected_raw, list):
            selected_indices = sorted({int(item) for item in selected_raw if isinstance(item, int) and item >= 0})
        elif isinstance(selected_raw, int) and selected_raw >= 0:
            selected_indices = [selected_raw]
        else:
            selected_indices = []
        if option_order:
            selected_indices = sorted(
                {
                    option_order[item]
                    for item in selected_indices
                    if item >= 0 and item < len(option_order)
                }
            )
        section_id = question.section_id if section_requires_full_score(question) else None
        bucket = scored_by_section.setdefault(section_id, {"earned": 0, "possible": 0})
        bucket["possible"] += question_points(question)
        if selected_indices == correct_indices:
            bucket["earned"] += question_points(question)

    for section_id, bucket in scored_by_section.items():
        if section_id is None or bucket["earned"] == bucket["possible"]:
            score += bucket["earned"]

    success_percent = (score / max_score) * 100 if max_score else 0
    passed = success_percent >= config.passing_percent
    attempt.score = score
    attempt.total_questions = total_questions
    attempt.max_score = max_score
    attempt.passed = passed
    attempt.status = AttemptStatus.COMPLETED.value if passed else AttemptStatus.FAILED.value
    attempt.ended_at = dt.datetime.utcnow()
    attempt.answers_json = json.dumps(payload.answers)
    db.commit()

    if passed:
        send_pass_notification_email(
            to_email=current_user.email,
            username=current_user.username,
            topic_name=config.topic_name,
            level_name=config.level_name,
            score_text=f"{score}/{max_score}",
        )

    db.refresh(current_user)
    return SubmitAttemptOut(
        attempt_id=attempt.id,
        passed=passed,
        score=score,
        total_questions=max_score,
        success_percent=round(success_percent, 2),
        remaining_credits=current_user.credits,
    )


@app.post("/tests/disqualify/{attempt_id}", response_model=SubmitAttemptOut)
def user_disqualify_test(
    attempt_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    attempt = db.get(Attempt, attempt_id)
    if attempt is None or attempt.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Attempt not found.")
    if attempt.status != AttemptStatus.IN_PROGRESS.value:
        raise HTTPException(status_code=400, detail="Attempt is already finalized.")

    config = db.get(TestConfig, attempt.test_config_id)
    if config is None:
        raise HTTPException(status_code=404, detail="Test config not found.")

    selected_ids = parse_selected_question_ids(attempt.selected_question_ids_json)
    if selected_ids:
        question_by_id = {question.id: question for question in config.questions}
        questions = [question_by_id[question_id] for question_id in selected_ids if question_id in question_by_id]
    else:
        questions = list(config.questions)
    max_score = attempt.max_score or sum(question_points(question) for question in questions)

    attempt.score = 0
    attempt.total_questions = len(questions)
    attempt.max_score = max_score
    attempt.passed = False
    attempt.status = AttemptStatus.DISQUALIFIED.value
    attempt.ended_at = dt.datetime.utcnow()
    attempt.answers_json = json.dumps({})
    db.commit()
    db.refresh(current_user)
    return SubmitAttemptOut(
        attempt_id=attempt.id,
        passed=False,
        score=0,
        total_questions=max_score,
        success_percent=0,
        remaining_credits=current_user.credits,
    )


@app.get("/social/dashboard", response_model=SocialDashboardOut)
def social_dashboard(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    return build_social_dashboard(db, current_user)


@app.get("/social/users/{user_id}/profile", response_model=SocialUserProfileOut)
def social_user_profile(
    user_id: int,
    _: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    target_user = db.get(User, user_id)
    if target_user is None or not target_user.is_active:
        raise HTTPException(status_code=404, detail="User not found.")
    return build_social_user_profile(db, target_user)


@app.get("/social/comments", response_model=list[SocialCommentOut])
def social_list_comments(
    _: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    test_config_id: int | None = Query(default=None),
):
    query = select(TestComment).order_by(TestComment.created_at.desc(), TestComment.id.desc())
    if test_config_id is not None:
        query = query.where(TestComment.test_config_id == test_config_id)
    comments = db.scalars(query.limit(200)).all()
    if not comments:
        return []
    user_ids = {item.user_id for item in comments}
    users = db.scalars(select(User).where(User.id.in_(user_ids))).all()
    username_map = {item.id: item.username for item in users}
    return [serialize_social_comment(item, username_map.get(item.user_id, "unknown")) for item in comments]


@app.post("/social/tests/{test_config_id}/comments", response_model=SocialCommentOut)
def social_add_comment(
    test_config_id: int,
    payload: SocialCommentCreateIn,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    config = db.get(TestConfig, test_config_id)
    if config is None or not is_content_published(config):
        raise HTTPException(status_code=404, detail="Test config not found.")
    content = payload.content.strip()
    if not content:
        raise HTTPException(status_code=400, detail="Comment cannot be empty.")
    comment = TestComment(
        test_config_id=test_config_id,
        user_id=current_user.id,
        content=content,
    )
    db.add(comment)
    db.commit()
    db.refresh(comment)
    return serialize_social_comment(comment, current_user.username)


@app.post("/social/follow/{target_user_id}")
def social_follow_user(
    target_user_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    if target_user_id == current_user.id:
        raise HTTPException(status_code=400, detail="You cannot follow yourself.")
    target_user = db.get(User, target_user_id)
    if target_user is None or not target_user.is_active:
        raise HTTPException(status_code=404, detail="Target user not found.")
    existing = db.scalar(
        select(UserFollow).where(
            UserFollow.follower_id == current_user.id,
            UserFollow.following_id == target_user_id,
        )
    )
    if existing is None:
        db.add(UserFollow(follower_id=current_user.id, following_id=target_user_id))
        db.commit()
    return {"following": True, "target_user_id": target_user_id}


@app.delete("/social/follow/{target_user_id}")
def social_unfollow_user(
    target_user_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    follow = db.scalar(
        select(UserFollow).where(
            UserFollow.follower_id == current_user.id,
            UserFollow.following_id == target_user_id,
        )
    )
    if follow is not None:
        db.delete(follow)
        db.commit()
    return {"following": False, "target_user_id": target_user_id}


@app.get("/profile/me", response_model=ProfileStatsOut)
def profile_me(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    attempts = db.scalars(select(Attempt).where(Attempt.user_id == current_user.id)).all()
    tests_done = len(attempts)
    passed_tests = len([item for item in attempts if item.passed])
    failed_tests = tests_done - passed_tests
    success_rate = (passed_tests / tests_done * 100) if tests_done else 0.0
    return ProfileStatsOut(
        user=serialize_user(current_user),
        tests_done=tests_done,
        passed_tests=passed_tests,
        failed_tests=failed_tests,
        success_rate_percent=round(success_rate, 2),
    )
