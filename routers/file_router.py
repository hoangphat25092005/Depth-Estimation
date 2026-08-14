from fastapi import APIRouter, UploadFile, File, Depends
from sqlalchemy.orm import Session

from typing import Annotated
from configs.database import get_db
from schemas.file import FileResponse, MultipleFileResponse
from services.file_service import upload_single_file, upload_multiple_files

router = APIRouter(
    prefix="/files", 
    tags=["Files"]
)

@router.post("/upload", response_model=FileResponse)
async def upload(file: UploadFile = File(...), db: Session = Depends(get_db)):
    return await upload_single_file(file, db)


@router.post(
    "/upload-multiple",
    response_model=MultipleFileResponse
)
async def upload_multiple_files_endpoint(files: Annotated[list[UploadFile], File(...)], db: Session = Depends(get_db)):
    uploaded_files = await upload_multiple_files(
        files=files,
        db=db
    )

    return {
        "files": uploaded_files
    }