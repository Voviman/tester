import datetime as dt
import hashlib
import json
import os
import secrets
import smtplib
from email.message import EmailMessage
from enum import Enum
from typing import Annotated

import jwt
from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, create_engine, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, relationship, sessionmaker


def normalize_database_url(url: str) -> str:
    value = (url or "").strip()
    if not value:
        return "sqlite:///./platform_backend.db"
    if value.startswith("postgres://"):
        value = value.replace("postgres://", "postgresql://", 1)
    if value.startswith("postgresql://"):
        value = value.replace("postgresql://", "postgresql+psycopg://", 1)
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


def serialize_user(user: User) -> UserOut:
    return UserOut(
        id=user.id,
        username=user.username,
        email=user.email,
        role=UserRole(user.role),
        credits=user.credits,
        is_active=user.is_active,
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


@app.patch("/admin/users/{user_id}/credits", response_model=UserOut)
def admin_add_user_credits(
    user_id: int,
    payload: CreditUpdateIn,
    _: Annotated[User, Depends(require_roles(UserRole.ADMIN, UserRole.SUPER_ADMIN))],
    db: Annotated[Session, Depends(get_db)],
):
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found.")
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
