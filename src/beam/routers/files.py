from fastapi import APIRouter, UploadFile, HTTPException
from starlette.responses import FileResponse
import secrets
from sqlalchemy.orm import Session
from beam import database
from datetime import datetime, timedelta
from sqlalchemy import select
from pathlib import Path
router = APIRouter()

@router.post('/upload')
async def upload(file: UploadFile):
    destination, file_id = await save_file(file)
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

    return {"destination" : destination}

async def save_file(file):
    chunk_size = 1024 * 1024 
    file_id = secrets.token_hex(6)
    
    destination = f"src/beam/uploads/{file_id}_{file.filename}"
    with open(destination, "wb") as f:
        while True:
            chunk = await file.read(chunk_size)
            if not chunk:
                break
            
            f.write(chunk)
    return destination, file_id

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
    query = select(database.File).where(
        database.File.expires_at <= datetime.now()
    )
    with Session(database.engine) as session:
        expired_files = session.scalars(query).all()
        for db_file in expired_files:
            #delete it from the physical location
            file_path = Path(f"src/beam/uploads/{db_file.file_id}_{db_file.file_name}")
            file_path.unlink(missing_ok=True)
            
            #delete the record in the database
            session.delete(db_file)
        session.commit()



    


    