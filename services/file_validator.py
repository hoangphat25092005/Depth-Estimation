from pathlib import Path
from fastapi import UploadFile, HTTPException

ALLOWED_TYPES = {
    "image/jpeg", 
    "image/png", 
    "image/webg", 
}

ALLOWED_EXTENSIONS = {
    ".jpg", 
    ".jpeg", 
    ".png", 
    ".webp"
}

MAX_SIZE_FILE = 10 * 1024 * 1024

async def validate_file(file: UploadFile):
    if file.content_type not in ALLOWED_TYPES:
        raise HTTPException(
            status_code=400, 
            detail="Invalid file type"
        )
    
    extension = Path(file.filename).suffix.lower()
    if extension not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400, 
            detail="Invalid File Extension!"
        )