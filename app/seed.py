from app.db import Base, engine


def create_tables() -> None:
    from app import models  # noqa: F401
    Base.metadata.create_all(bind=engine)
    print("[OK] Tables created (or already existed)")


if __name__ == "__main__":
    create_tables()
    print("\nSetup complete. Run:  python run.py")
    print("Then open http://localhost:8000 and sign up to create the first admin.")
