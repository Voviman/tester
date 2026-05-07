import datetime as dt
import hashlib
import json
import os
import secrets
import smtplib
from email.message import EmailMessage
from enum import Enum
from typing import Annotated
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import jwt
from fastapi import Depends, FastAPI, HTTPException, Query, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, create_engine, func, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, relationship, sessionmaker


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

SMTP_HOST = os.getenv("SMTP_HOST", "")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USERNAME = os.getenv("SMTP_USERNAME", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
SMTP_SENDER = os.getenv("SMTP_SENDER", SMTP_USERNAME or "noreply@example.com")

engine = create_engine(DATABASE_URL, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


class Base(DeclarativeBase):
    pass


class UserRole(str, Enum):
    SUPER_ADMIN = "super_admin"
    ADMIN = "admin"
    USER = "user"


class AttemptStatus(str, Enum):
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"


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


class TestConfig(Base):
    __tablename__ = "test_configs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    topic_name: Mapped[str] = mapped_column(String(120), index=True)
    level_name: Mapped[str] = mapped_column(String(120), index=True)
    duration_seconds: Mapped[int] = mapped_column(Integer, default=900)
    passing_percent: Mapped[float] = mapped_column(Float, default=60.0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    questions: Mapped[list["Question"]] = relationship(back_populates="test_config", cascade="all,delete")
    attempts: Mapped[list["Attempt"]] = relationship(back_populates="test_config")


class Question(Base):
    __tablename__ = "questions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    test_config_id: Mapped[int] = mapped_column(ForeignKey("test_configs.id"))
    question_text: Mapped[str] = mapped_column(Text)
    options_json: Mapped[str] = mapped_column(Text)
    correct_index: Mapped[int] = mapped_column(Integer)

    test_config: Mapped[TestConfig] = relationship(back_populates="questions")


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


def parse_options(options_json: str) -> list[str]:
    try:
        value = json.loads(options_json)
    except json.JSONDecodeError as error:
        raise HTTPException(status_code=500, detail="Invalid options data in database.") from error
    if not isinstance(value, list):
        raise HTTPException(status_code=500, detail="Invalid options format in database.")
    return [str(item) for item in value]


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


class TestConfigOut(BaseModel):
    id: int
    topic_name: str
    level_name: str
    duration_seconds: int
    passing_percent: float
    is_active: bool
    question_count: int


class QuestionCreateIn(BaseModel):
    test_config_id: int
    question_text: str = Field(min_length=5)
    options: list[str] = Field(min_length=4, max_length=4)
    correct_index: int = Field(ge=0, le=3)


class QuestionPublicOut(BaseModel):
    id: int
    question_text: str
    options: list[str]


class QuestionAdminOut(QuestionPublicOut):
    test_config_id: int
    correct_index: int


class TestStartOut(BaseModel):
    attempt_id: int
    duration_seconds: int
    passing_percent: float
    remaining_credits: int
    questions: list[QuestionPublicOut]


class SubmitAttemptIn(BaseModel):
    answers: dict[int, int]


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


class UserAdminStatsOut(BaseModel):
    user: UserOut
    tests_done: int
    passed_tests: int
    failed_tests: int
    success_rate_percent: float
    attempts: list[AttemptAdminOut]


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


class QuestionUpdateIn(BaseModel):
    question_text: str | None = Field(default=None, min_length=5)
    options: list[str] | None = Field(default=None, min_length=4, max_length=4)
    correct_index: int | None = Field(default=None, ge=0, le=3)


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
    tests_done: int
    success_rate_percent: float
    follower_count: int


class SocialResultOut(BaseModel):
    attempt_id: int
    user_id: int
    username: str
    topic_name: str
    level_name: str
    score: int
    total_questions: int
    passed: bool
    success_percent: float
    ended_at: dt.datetime | None


class SocialDashboardOut(BaseModel):
    tests: list[TestConfigOut]
    active_users: list[SocialActiveUserOut]
    recent_results: list[SocialResultOut]
    following_user_ids: list[int]


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
    return QuestionAdminOut(
        id=question.id,
        test_config_id=question.test_config_id,
        question_text=question.question_text,
        options=parse_options(question.options_json),
        correct_index=question.correct_index,
    )


def can_manage_target_user(current_user: User, target_user: User) -> bool:
    if current_user.role == UserRole.SUPER_ADMIN.value:
        return True
    if current_user.role == UserRole.ADMIN.value:
        return target_user.role == UserRole.USER.value
    return False


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
                total_questions=item.total_questions,
                passed=item.passed,
                started_at=item.started_at,
                ended_at=item.ended_at,
                topic_name=config.topic_name if config else "Unknown",
                level_name=config.level_name if config else "Unknown",
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
    tests = db.scalars(
        select(TestConfig)
        .where(TestConfig.is_active.is_(True))
        .order_by(TestConfig.topic_name.asc(), TestConfig.level_name.asc())
    ).all()
    tests_out = [
        TestConfigOut(
            id=item.id,
            topic_name=item.topic_name,
            level_name=item.level_name,
            duration_seconds=item.duration_seconds,
            passing_percent=item.passing_percent,
            is_active=item.is_active,
            question_count=len(item.questions),
        )
        for item in tests
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
        total = max(attempt.total_questions, 1)
        success_percent = (attempt.score / total) * 100
        recent_results.append(
            SocialResultOut(
                attempt_id=attempt.id,
                user_id=user.id,
                username=user.username,
                topic_name=config.topic_name,
                level_name=config.level_name,
                score=attempt.score,
                total_questions=attempt.total_questions,
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
                    tests_done=tests_done,
                    success_rate_percent=round(success_rate, 2),
                    follower_count=follower_counts.get(user.id, 0),
                )
            )
        active_users.sort(key=lambda item: (-item.tests_done, item.username.lower()))

    return SocialDashboardOut(
        tests=tests_out,
        active_users=active_users[:30],
        recent_results=recent_results,
        following_user_ids=following_user_ids,
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


@app.on_event("startup")
def on_startup():
    Base.metadata.create_all(bind=engine)


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


@app.get("/admin/users", response_model=list[UserOut])
def admin_list_users(
    _: Annotated[User, Depends(require_roles(UserRole.ADMIN, UserRole.SUPER_ADMIN))],
    db: Annotated[Session, Depends(get_db)],
):
    users = db.scalars(select(User).order_by(User.id.asc())).all()
    return [serialize_user(user) for user in users]


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


@app.post("/admin/users", response_model=UserOut)
def admin_create_user(
    payload: UserCreateIn,
    current_user: Annotated[User, Depends(require_roles(UserRole.ADMIN, UserRole.SUPER_ADMIN))],
    db: Annotated[Session, Depends(get_db)],
):
    if payload.role == UserRole.SUPER_ADMIN:
        raise HTTPException(status_code=403, detail="Cannot create another super admin through this endpoint.")
    if current_user.role == UserRole.ADMIN.value and payload.role != UserRole.USER:
        raise HTTPException(status_code=403, detail="Admins can only create regular users.")

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
    if current_user.role == UserRole.ADMIN.value and payload.role is not None and payload.role != UserRole.USER:
        raise HTTPException(status_code=403, detail="Admins can only assign user role.")

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


@app.post("/admin/test-configs", response_model=TestConfigOut)
def admin_upsert_test_config(
    payload: TestConfigCreateIn,
    _: Annotated[User, Depends(require_roles(UserRole.ADMIN, UserRole.SUPER_ADMIN))],
    db: Annotated[Session, Depends(get_db)],
):
    existing = db.scalar(
        select(TestConfig).where(
            TestConfig.topic_name == payload.topic_name.strip(),
            TestConfig.level_name == payload.level_name.strip(),
        )
    )
    if existing:
        existing.duration_seconds = payload.duration_seconds
        existing.passing_percent = payload.passing_percent
        existing.is_active = payload.is_active
        db.commit()
        db.refresh(existing)
        question_count = len(existing.questions)
        return TestConfigOut(
            id=existing.id,
            topic_name=existing.topic_name,
            level_name=existing.level_name,
            duration_seconds=existing.duration_seconds,
            passing_percent=existing.passing_percent,
            is_active=existing.is_active,
            question_count=question_count,
        )

    config = TestConfig(
        topic_name=payload.topic_name.strip(),
        level_name=payload.level_name.strip(),
        duration_seconds=payload.duration_seconds,
        passing_percent=payload.passing_percent,
        is_active=payload.is_active,
    )
    db.add(config)
    db.commit()
    db.refresh(config)
    return TestConfigOut(
        id=config.id,
        topic_name=config.topic_name,
        level_name=config.level_name,
        duration_seconds=config.duration_seconds,
        passing_percent=config.passing_percent,
        is_active=config.is_active,
        question_count=0,
    )


@app.get("/admin/test-configs", response_model=list[TestConfigOut])
def admin_list_test_configs(
    _: Annotated[User, Depends(require_roles(UserRole.ADMIN, UserRole.SUPER_ADMIN))],
    db: Annotated[Session, Depends(get_db)],
):
    configs = db.scalars(select(TestConfig).order_by(TestConfig.topic_name, TestConfig.level_name)).all()
    result = []
    for config in configs:
        result.append(
            TestConfigOut(
                id=config.id,
                topic_name=config.topic_name,
                level_name=config.level_name,
                duration_seconds=config.duration_seconds,
                passing_percent=config.passing_percent,
                is_active=config.is_active,
                question_count=len(config.questions),
            )
        )
    return result


@app.patch("/admin/test-configs/{test_config_id}", response_model=TestConfigOut)
def admin_update_test_config(
    test_config_id: int,
    payload: TestConfigUpdateIn,
    _: Annotated[User, Depends(require_roles(UserRole.ADMIN, UserRole.SUPER_ADMIN))],
    db: Annotated[Session, Depends(get_db)],
):
    config = db.get(TestConfig, test_config_id)
    if config is None:
        raise HTTPException(status_code=404, detail="Test config not found.")

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

    db.commit()
    db.refresh(config)
    return TestConfigOut(
        id=config.id,
        topic_name=config.topic_name,
        level_name=config.level_name,
        duration_seconds=config.duration_seconds,
        passing_percent=config.passing_percent,
        is_active=config.is_active,
        question_count=len(config.questions),
    )


@app.post("/admin/questions", response_model=QuestionPublicOut)
def admin_add_question(
    payload: QuestionCreateIn,
    _: Annotated[User, Depends(require_roles(UserRole.ADMIN, UserRole.SUPER_ADMIN))],
    db: Annotated[Session, Depends(get_db)],
):
    config = db.get(TestConfig, payload.test_config_id)
    if config is None:
        raise HTTPException(status_code=404, detail="Test config not found.")
    cleaned_options = [item.strip() for item in payload.options]
    if any(not item for item in cleaned_options):
        raise HTTPException(status_code=400, detail="All options are required.")
    if len(set(item.lower() for item in cleaned_options)) != len(cleaned_options):
        raise HTTPException(status_code=400, detail="Question options must be unique.")

    question = Question(
        test_config_id=payload.test_config_id,
        question_text=payload.question_text.strip(),
        options_json=json.dumps(cleaned_options),
        correct_index=payload.correct_index,
    )
    db.add(question)
    db.commit()
    db.refresh(question)
    return QuestionPublicOut(id=question.id, question_text=question.question_text, options=cleaned_options)


@app.get("/admin/questions", response_model=list[QuestionAdminOut])
def admin_list_questions(
    _: Annotated[User, Depends(require_roles(UserRole.ADMIN, UserRole.SUPER_ADMIN))],
    db: Annotated[Session, Depends(get_db)],
    test_config_id: int | None = Query(default=None),
):
    query = select(Question).order_by(Question.id.desc())
    if test_config_id is not None:
        query = query.where(Question.test_config_id == test_config_id)
    questions = db.scalars(query).all()
    return [serialize_question_admin(item) for item in questions]


@app.patch("/admin/questions/{question_id}", response_model=QuestionAdminOut)
def admin_update_question(
    question_id: int,
    payload: QuestionUpdateIn,
    _: Annotated[User, Depends(require_roles(UserRole.ADMIN, UserRole.SUPER_ADMIN))],
    db: Annotated[Session, Depends(get_db)],
):
    question = db.get(Question, question_id)
    if question is None:
        raise HTTPException(status_code=404, detail="Question not found.")

    if payload.question_text is not None:
        question.question_text = payload.question_text.strip()

    options = parse_options(question.options_json)
    if payload.options is not None:
        cleaned_options = [item.strip() for item in payload.options]
        if any(not item for item in cleaned_options):
            raise HTTPException(status_code=400, detail="All options are required.")
        if len(set(item.lower() for item in cleaned_options)) != len(cleaned_options):
            raise HTTPException(status_code=400, detail="Question options must be unique.")
        options = cleaned_options
        question.options_json = json.dumps(cleaned_options)

    if payload.correct_index is not None:
        question.correct_index = payload.correct_index
    elif question.correct_index >= len(options):
        raise HTTPException(status_code=400, detail="Correct index is out of bounds for provided options.")

    db.commit()
    db.refresh(question)
    return serialize_question_admin(question)


@app.delete("/admin/questions/{question_id}")
def admin_delete_question(
    question_id: int,
    _: Annotated[User, Depends(require_roles(UserRole.ADMIN, UserRole.SUPER_ADMIN))],
    db: Annotated[Session, Depends(get_db)],
):
    question = db.get(Question, question_id)
    if question is None:
        raise HTTPException(status_code=404, detail="Question not found.")
    db.delete(question)
    db.commit()
    return {"deleted": True}


@app.get("/tests/catalog", response_model=list[TestConfigOut])
def user_list_test_catalog(
    _: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    configs = db.scalars(
        select(TestConfig).where(TestConfig.is_active.is_(True)).order_by(TestConfig.topic_name, TestConfig.level_name)
    ).all()
    items = []
    for config in configs:
        items.append(
            TestConfigOut(
                id=config.id,
                topic_name=config.topic_name,
                level_name=config.level_name,
                duration_seconds=config.duration_seconds,
                passing_percent=config.passing_percent,
                is_active=config.is_active,
                question_count=len(config.questions),
            )
        )
    return items


@app.post("/tests/start/{test_config_id}", response_model=TestStartOut)
def user_start_test(
    test_config_id: int,
    current_user: Annotated[User, Depends(require_roles(UserRole.USER, UserRole.ADMIN, UserRole.SUPER_ADMIN))],
    db: Annotated[Session, Depends(get_db)],
):
    config = db.get(TestConfig, test_config_id)
    if config is None or not config.is_active:
        raise HTTPException(status_code=404, detail="Test config not found or inactive.")
    if current_user.credits < 1:
        raise HTTPException(status_code=402, detail="Insufficient credits. 1 credit is required per test try.")
    if len(config.questions) == 0:
        raise HTTPException(status_code=400, detail="This test has no questions yet.")

    current_user.credits -= 1
    attempt = Attempt(user_id=current_user.id, test_config_id=config.id, status=AttemptStatus.IN_PROGRESS.value)
    db.add(attempt)
    db.commit()
    db.refresh(attempt)

    # We return a randomized question order for each attempt session.
    shuffled_questions = list(config.questions)
    secrets.SystemRandom().shuffle(shuffled_questions)
    questions_out = [
        QuestionPublicOut(
            id=question.id,
            question_text=question.question_text,
            options=parse_options(question.options_json),
        )
        for question in shuffled_questions
    ]
    return TestStartOut(
        attempt_id=attempt.id,
        duration_seconds=config.duration_seconds,
        passing_percent=config.passing_percent,
        remaining_credits=current_user.credits,
        questions=questions_out,
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

    questions = list(config.questions)
    if not questions:
        raise HTTPException(status_code=400, detail="No questions configured for this test.")

    score = 0
    total_questions = len(questions)
    answer_map = payload.answers

    for question in questions:
        selected_index = answer_map.get(question.id, -1)
        if selected_index == question.correct_index:
            score += 1

    success_percent = (score / total_questions) * 100
    passed = success_percent >= config.passing_percent
    attempt.score = score
    attempt.total_questions = total_questions
    attempt.passed = passed
    attempt.status = AttemptStatus.COMPLETED.value if passed else AttemptStatus.FAILED.value
    attempt.ended_at = dt.datetime.utcnow()
    db.commit()

    if passed:
        send_pass_notification_email(
            to_email=current_user.email,
            username=current_user.username,
            topic_name=config.topic_name,
            level_name=config.level_name,
            score_text=f"{score}/{total_questions}",
        )

    db.refresh(current_user)
    return SubmitAttemptOut(
        attempt_id=attempt.id,
        passed=passed,
        score=score,
        total_questions=total_questions,
        success_percent=round(success_percent, 2),
        remaining_credits=current_user.credits,
    )


@app.get("/social/dashboard", response_model=SocialDashboardOut)
def social_dashboard(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    return build_social_dashboard(db, current_user)


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
    if config is None or not config.is_active:
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
