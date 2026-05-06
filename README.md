# Desktop Testing Application

This project is a desktop testing system built with Python and Tkinter.

## Features

- Admin login with username/password
- Admin panel with:
  - Results table (test history)
  - Add topics
  - Add levels
  - Add questions (4 options + correct answer)
- Candidate registration:
  - Enter name
  - Select topic
  - Select level
- Anti-cheat:
  - Focus loss (for example alt-tab) counts as a violation
  - Up to 5 violations are allowed
  - More than 5 violations auto-fails and ends the test
- Session randomization:
  - Question order is shuffled every session
  - Answer options are shuffled every session

## Run

1. Install Python 3.10+.
2. Run:

```powershell
python app.py
```

## Default Admin Login

- Username: `admin`
- Password: `admin123`

The database file `testing_app.db` is created automatically on first run.

## New: Internet-Hosted Platform Backend

To support shared credentials between website + desktop app, web-based admin panel, credits, configurable timers, and profile statistics, this repository now includes `platform_api.py` (FastAPI backend).

### What it adds

- Separate API + database layer that can be hosted independently from clients
- Role-based users:
  - `super_admin` can create `admin` and `user`
  - `admin` can create `user` and add credits
- Shared login credentials for all clients (website + desktop)
- Credits model (`1 credit = 1 test try`)
- Admin-managed test settings:
  - `duration_seconds` (custom timer)
  - `passing_percent` (required success rate)
- Successful test pass email notification (SMTP-based)
- User profile endpoint with:
  - total tests done
  - passed/failed count
  - success rate percent

### Run the backend

1. Install dependencies:

```powershell
pip install -r platform_requirements.txt
```

2. (Optional but recommended) configure environment variables:

- `DATABASE_URL` (example: PostgreSQL URL in production)
- `JWT_SECRET`
- `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `SMTP_SENDER`

3. Start API server:

```powershell
uvicorn platform_api:app --host 0.0.0.0 --port 8000 --reload
```

4. Open API docs:

- `http://localhost:8000/docs`

### First-time setup flow

1. Call `POST /auth/bootstrap-super-admin` once to create first super admin.
2. Login using `POST /auth/login`.
3. Super admin creates admins via `POST /admin/users`.
4. Admin creates users and adds credits via:
   - `POST /admin/users`
   - `PATCH /admin/users/{user_id}/credits`
5. Admin configures tests:
   - `POST /admin/test-configs`
   - `POST /admin/questions`
