import logging

from .config import Settings
from .http_api import serve


def main() -> None:
    settings = Settings.from_env()
    if not settings.token:
        logging.warning("STATUS_API_TOKEN is empty; protected endpoints will return 401")
    serve(settings)


if __name__ == "__main__":
    main()
