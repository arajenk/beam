from fastapi import FastAPI
from beam.routers import files

app = FastAPI()
app.include_router(files.router)
