from fastapi import APIRouter, UploadFile, HTTPException
from starlette.responses import FileResponse
import secrets
from sqlalchemy.orm import Session
from beam import database
from datetime import datetime, timedelta
from sqlalchemy import select
from pathlib import Path

class UploadTooLarge(Exception):
    pass

router = APIRouter()

@router.post('/upload')
async def upload(file: UploadFile):
    try:
        file_id = await save_file(file)
    except UploadTooLarge:
        raise HTTPException(status_code=413, detail="File is too large")

    now = datetime.now()
    expires_at = now + timedelta(hours=12)
    
    file_record = database.File(
        file_id = file_id,
        file_name = file.filename,
        expires_at = expires_at
    )
    with Session(database.engine) as session:
        session.add(file_record)
        session.commit()
    cleanup()

    return {
        "file_id": file_id,
        "expires_at": expires_at
    }

async def save_file(file):
    CHUNK_SIZE = 1024 * 1024
    file_id = secrets.token_hex(6)
    MAX_SIZE = 10 * 1024 * 1024 * 1024
    destination = f"src/beam/uploads/{file_id}_{file.filename}"
    if file.size is not None and file.size > MAX_SIZE:
        raise UploadTooLarge
    with open(destination, "wb") as f:
        total_size = 0
        while True:
            chunk = await file.read(CHUNK_SIZE)
            if not chunk:
                break
            total_size += len(chunk)

            if total_size > MAX_SIZE:
                Path(destination).unlink(missing_ok=True)
                raise UploadTooLarge
            f.write(chunk)

        return file_id

@router.get('/f/{file_id}')
def download(file_id: str):
    with Session(database.engine) as session:
        db_file = session.get(database.File, file_id)  
    
        if db_file:
            if db_file.expires_at > datetime.now():
                stored_path = f"src/beam/uploads/{file_id}_{db_file.file_name}"
                return FileResponse(
                    path=stored_path, 
                    filename=db_file.file_name
                )
            else:
                raise HTTPException(status_code=410, detail="File has expired")
        raise HTTPException(status_code=404, detail="File not found")
        
def cleanup():
    #kill expired files
    query = select(database.File).where(
        database.File.expires_at <= datetime.now()
    )
    with Session(database.engine) as session:
        expired_files = session.scalars(query).all()
        for db_file in expired_files:
            file_path = Path(f"src/beam/uploads/{db_file.file_id}_{db_file.file_name}")
            file_path.unlink(missing_ok=True)
            
            session.delete(db_file)
        session.commit()

    #orphan killer
    path = Path("src/beam/uploads")

    id_query = select(database.File.file_id)
    with Session(database.engine) as session:
        id_set = set(session.scalars(id_query))
    for file in path.iterdir():
        file_id = file.name.split("_", 1)[0]
        if file_id not in id_set:
            file.unlink(missing_ok=True)


    


    