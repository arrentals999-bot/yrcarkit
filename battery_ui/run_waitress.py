"""Launch the battery UI with waitress (production WSGI server)."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from battery_ui.app import app
from waitress import serve
print("Starting waitress on http://127.0.0.1:5000 with 8 threads")
serve(app, host="127.0.0.1", port=5000, threads=8)
