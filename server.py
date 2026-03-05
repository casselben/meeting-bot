# server.py
from dotenv import load_dotenv
load_dotenv()

from app.pythonHowToBuildABot import app
from app.analyze import router as analysis_router

# Mount additional routes under /api
app.include_router(analysis_router, prefix="/api")

if __name__ == "__main__":
    import uvicorn
    print("[boot] starting Recall.ai bot server...")
    uvicorn.run(app, host="0.0.0.0", port=8000, reload=False)
