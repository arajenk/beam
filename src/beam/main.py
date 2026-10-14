import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
import os
from beam.routers import files, reports

load_dotenv()

@asynccontextmanager
async def lifespan(app):
    sweeper = asyncio.create_task(files.sweep_loop())
    yield
    sweeper.cancel()


app = FastAPI(lifespan=lifespan)

# the frontend lives on a different origin, so browsers need permission to read our responses
cors_origins = os.environ.get("CORS_ORIGINS", "http://localhost:5173").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in cors_origins if o.strip()],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

app.include_router(files.router)
app.include_router(reports.router)
