"""Single entrypoint to run the application."""
import argparse
import uvicorn

from app.config import settings


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default=settings.HOST)
    ap.add_argument("--port", type=int, default=settings.PORT)
    ap.add_argument("--no-reload", action="store_true")
    args = ap.parse_args()

    print(f"  {settings.APP_NAME}")
    print(f"  Dashboard:  http://{args.host}:{args.port}/")
    print(f"  API docs:   http://{args.host}:{args.port}/docs")
    print()

    uvicorn.run(
        "app.main:app", host=args.host, port=args.port,
        reload=not args.no_reload and settings.DEBUG,
        log_level="info",
    )


if __name__ == "__main__":
    main()
