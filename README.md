# AI Smart House Prediction System

A locally runnable Flask application for early house, land, cost and water planning. Predictions use transparent, deterministic demo heuristics; this project does not include a trained ML model, live LLM integration, verified groundwater feed, email delivery, or certified engineering/legal advice. Water values are only those entered by the user.

## Run in VS Code (PowerShell)

Open this project folder in VS Code, then open **Terminal → New Terminal** and run:

```powershell
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
venv\Scripts\python.exe -m pip install -r requirements.txt
venv\Scripts\python.exe -m flask --app app upgrade-auth-schema
venv\Scripts\python.exe -m flask --app app init-db
venv\Scripts\python.exe -m flask --app app run --debug
```

Open http://127.0.0.1:5000. The upgrade command is safe to rerun: it creates any missing app tables, adds `full_name` and `phone` to an existing `users` table when needed, and copies old `name` values into `full_name`. It does not drop tables or user/project rows. Keep your existing `DATABASE_URL` in `.env`; if absent the app uses its existing SQLite database at `instance/smart_house.db`.

To use MySQL, set `DATABASE_URL` in `.env` to `mysql+pymysql://user:password@localhost/smart_house?charset=utf8mb4` before running the commands. For an existing MySQL database, run `flask --app app upgrade-auth-schema`; do not re-run the `CREATE TABLE` statements in `database.sql`. For a new MySQL database, create the database, set `DATABASE_URL`, and use `flask --app app init-db` to create the application tables and sample categories. The SQL file remains a reference schema for new installations.

New users register at `/register`, then sign in at `/login`. Registration requires a unique email, valid phone number, matching passwords and a password of at least 8 characters. Passwords are stored as Werkzeug hashes. Login cookies are non-persistent browser-session cookies; set `SESSION_COOKIE_SECURE=1` when serving over HTTPS. Demo administrator: `admin@smarthouse.local` / `Admin123!` unless `ADMIN_PASSWORD` was set before database initialization; change the demo credential before exposing the app.

## Included modules

- Password-hashed registration/login/logout, session-only sign-in, a non-cached protected area, profile page and user-scoped dashboard records.
- House category gallery and save/unsave actions; admin category and regional-rate CRUD.
- Rule-based house recommendation and budget estimate with saved prediction history.
- Land suitability heuristic, water-level records with history chart, and planning assistant with saved chat history.
- Responsive Bootstrap 5 layout and Chart.js water history.

Cost rates are editable starting assumptions, not a current quote. Water charts show user-entered records only. Land/building fit scores are simulated planning indicators. Have site, groundwater, document, and structural questions reviewed by appropriate local professionals.
