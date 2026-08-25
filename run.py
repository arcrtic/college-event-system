import os

from app import create_app

app = create_app()

if __name__ == "__main__":
    # PORT is read for hosts like Render/Railway, which assign it dynamically;
    # locally it just falls back to Flask's default of 5000.
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=app.config["DEBUG"])
