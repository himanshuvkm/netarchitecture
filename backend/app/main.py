import logging
import os
from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
from .api.routes import router

load_dotenv(Path(__file__).resolve().parents[2] / ".env")
logging.basicConfig(level=os.getenv("NETARCHITECT_LOG_LEVEL", "INFO"))
app = FastAPI(title="NetArchitect Recommendation & Config Engine", version="1.0.0")
origins = [origin.strip() for origin in os.getenv("NETARCHITECT_CORS_ORIGINS", "http://localhost:5173").split(",") if origin.strip()]
app.add_middleware(CORSMiddleware, allow_origins=origins, allow_methods=["GET", "POST"], allow_headers=["Content-Type"])
app.include_router(router)
