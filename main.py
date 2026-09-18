import os
import uvicorn
from src.server import app

# Render dynamically assigns a port via environment variables, 
# defaulting to 8000 if testing locally.
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("src.server:app", host="0.0.0.0", port=port)