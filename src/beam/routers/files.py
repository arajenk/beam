from fastapi import APIRouter, UploadFile
import secrets
router = APIRouter()

@router.post('/upload')
async def upload(file: UploadFile):
    destination = await save_file(file)
    return {"destination" : destination}

async def save_file(file):
    size = 1024 * 1024 
    file_id = secrets.token_hex(6)
    
    destination = f"src/beam/uploads/{file_id}_{file.filename}"
    with open(destination, "wb") as f:
        while True:
            chunk = await file.read(size)
            if not chunk:
                break
            
            f.write(chunk)
    return destination
            


    