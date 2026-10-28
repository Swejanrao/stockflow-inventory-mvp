# StockFlow MVP

A small multi-tenant inventory management app built with Flask, SQLAlchemy, Flask-Login, PostgreSQL (production) and Bootstrap.

## Features
- Email/password signup and login; passwords are hashed.
- Signup creates an organization and links the user to it.
- Product create, list, search, edit and delete.
- Product fields: name, organization-scoped SKU, optional description, quantity, cost price, selling price, optional low-stock threshold.
- Dashboard totals and low-stock list.
- Organization-specific default low-stock threshold (default 5).
- Organization scoping is applied to product queries and edits/deletes.
- CSRF protection on POST forms.

## Run locally (Windows PowerShell)

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
python app.py
```

Open http://127.0.0.1:5000. Local development uses SQLite and creates `instance/stockflow.db` automatically.

If PowerShell blocks activation, run this in the current terminal only:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```

## Production environment variables
- `SECRET_KEY`: long random secret; never commit it.
- `DATABASE_URL`: PostgreSQL connection string from your hosted database.

Set both in your hosting provider's environment settings. Use a persistent PostgreSQL database in production; the local SQLite file is for development only.

## Deploy on Render
1. Push this repository to GitHub.
2. Create a managed PostgreSQL database in Render and copy its internal connection URL.
3. Create a Render Web Service connected to the GitHub repository.
4. Build command: `pip install -r requirements.txt`
5. Start command: `gunicorn app:app`
6. Add `SECRET_KEY` and `DATABASE_URL` in the web service environment settings.
7. Deploy, open the generated URL, sign up, and test the features below.

## Demo checklist
1. Sign up with a test email, password and organization name.
2. Create a product with quantity 3 and leave its threshold blank. With the default threshold 5, it should appear as low stock.
3. Create a product with quantity 20 and threshold 5; it should show as in stock.
4. Search by name and SKU; edit quantity; confirm dashboard totals update.
5. Change the organization default threshold in Settings and confirm blank-threshold products follow the new value.
6. Delete a product and confirm the dialog appears first.
7. Create a second test account with another organization and verify it cannot see the first account's products.

## MVP notes
- One owner user per organization is assumed. There are no invites, roles, password reset, stock movement history, imports, integrations or billing.
- Product delete is hard delete, as allowed by the brief.
- Prices are displayed with `$` as a simple demo convention; change the currency label if your demo requires another currency.
- `db.create_all()` creates tables for a fresh database. For a larger production app, add versioned migrations (for example Flask-Migrate/Alembic) before schema changes.
