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
