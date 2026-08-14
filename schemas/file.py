from datetime import datetime
from typing import Optional
from pydantic import BaseModel

class FileResponse(BaseModel):
    id: int
    original_filename: str
    stored_filename: str
    bucket_name: str
    content_type: str
    file_size: int
    file_url: Optional[str] = None
    created_at: datetime

    model_config = {
        "from_attributes": True
    }

class MultipleFileResponse(BaseModel):
    files: list[FileResponse]

class DepthEstimationResponse(BaseModel):
    original_image: FileResponse
    depth_image: FileResponse