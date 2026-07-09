"""WSGI entry point for gunicorn."""
import os
import sys

# Ensure project root is on sys.path
project_root = os.path.dirname(os.path.abspath(__file__))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from interface.api import app as application

# gunicorn can use either `app` or `application`
app = application
