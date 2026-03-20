"""
main.py — convenience entry point.

Delegates entirely to app.py's create_app factory.
Run with: python main.py
"""

from app import create_app

app = create_app()

if __name__ == "__main__":
    app.run(debug=True, port=5001)
