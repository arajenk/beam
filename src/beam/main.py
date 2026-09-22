from fastapi import FastAPI
from beam.routers import files

app = FastAPI()
app.include_router(files.router)

@app.get('/')
async def running():
    return {"message": "Beam is running"}