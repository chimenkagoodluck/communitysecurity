"""
Database setup.

Run once after install (optional — the app also creates its tables automatically
on startup):
    python -m app.seed

This only creates the database tables. It does NOT create any users or demo data.
The first person to sign up at /signup becomes the administrator; the database
starts completely empty and fills up only through real use of the app.
"""
from app.db import Base, engine


def create_tables() -> None:
    from app import models  # noqa: F401
    Base.metadata.create_all(bind=engine)
    print("[OK] Tables created (or already existed)")


if __name__ == "__main__":
    create_tables()
    print("\nSetup complete. Run:  python run.py")
    print("Then open http://localhost:8000 and sign up to create the first admin.")
