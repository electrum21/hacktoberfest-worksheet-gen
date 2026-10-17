"""Production entry point: gunicorn -b 0.0.0.0:8000 portal.wsgi:app"""
from .server import create_app

app = create_app()
