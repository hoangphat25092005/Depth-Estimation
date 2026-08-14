from sqlalchemy import Column, Integer, String, BigInteger, DateTime, ForeignKey
from sqlalchemy.sql import func

from configs.database import Base
from configs.setting import STORAGE_DOMAIN

class FileModel(Base):
    __tablename__ = "files"

    @property
    def file_url(self) -> str:
        # Lấy domain từ biến môi trường
        domain = STORAGE_DOMAIN
        # Tự động sinh ra link đúng chuẩn nhờ self.bucket_name
        return f"{domain}/{self.bucket_name}/{self.stored_filename}"

    id = Column(
        Integer, 
        primary_key=True, 
        index=True
    )

    original_filename = Column(
        String(100), 
        nullable=False, 
    )

    stored_filename = Column(
        String(255), 
        nullable=False, 
        unique=True
    )

    content_type = Column(
        String(100), 
        nullable=False
    )

    file_size = Column(
        BigInteger, 
        nullable=False
    )

    bucket_name = Column(
        String(100), 
        nullable=False
    )

    created_at = Column(
        DateTime, 
        server_default=func.now()
    )

    status = Column(String(20), default="processing")

    depth_file_id = Column(Integer, ForeignKey("files.id"), nullable=True)