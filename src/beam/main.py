from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
import os
from beam.routers import files

load_dotenv()

app = FastAPI()

# the frontend lives on a different origin, so browsers need permission to read our responses
cors_origins = os.environ.get("CORS_ORIGINS", "http://localhost:5173").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in cors_origins if o.strip()],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

app.include_router(files.router)
