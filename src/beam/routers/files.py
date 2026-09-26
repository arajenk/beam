from fastapi import APIRouter, UploadFile, HTTPException
from starlette.responses import FileResponse
import secrets
from sqlalchemy.orm import Session
from beam import database
router = APIRouter()

@router.post('/upload')
async def upload(file: UploadFile):
    destination, file_id = await save_file(file)

    file_record = database.File(
        file_id = file_id,
        file_name = file.filename
    )
    with Session(database.engine) as session:
        session.add(file_record)
        session.commit()

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
            stored_path = f"src/beam/uploads/{file_id}_{db_file.file_name}"
            return FileResponse(
                path=stored_path, 
                filename=db_file.file_name
            )
        raise HTTPException(status_code=404, detail="File not found")
        


    


    