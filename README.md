# PartVault

PartVault is a simple Flask-based inventory management app for tracking parts and related data.

## Features
- Upload and manage part data
- Store part records in a SQLite database
- Simple web interface for viewing and managing inventory

## Requirements
Install the dependencies with:

```bash
pip install -r requirements.txt
```

## Run the app
```bash
python app.py
```

Then open your browser to the local address shown by Flask.

## Project structure
- `app.py` — application entry point
- `routes.py` — route definitions
- `models.py` — database models
- `bulk_imports.py` — bulk import logic
- `config.py` — configuration settings
- `index.html` — main UI template
