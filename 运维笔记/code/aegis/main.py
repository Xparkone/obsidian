from app.config import load_settings
from app.server import serve


if __name__ == "__main__":
    serve(load_settings())
