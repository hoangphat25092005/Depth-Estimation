from contextlib import asynccontextmanager
from fastapi import FastAPI
from configs.database import database_engine
from configs.database import Base
from models.file import FileModel
from routers.file_router import router as file_router
from routers.depth_router import router as depth_router

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Create database tables
    Base.metadata.create_all(bind=database_engine)
    print("Đang khởi động và khởi tạo Database")
    yield
    print("Đang tắt server và dọn dẹp tài nguyên...")


# main FastAPI Application
app = FastAPI(
    title="File Upload System", 
    description="A File upload API built with FastAPI and MySQL",
    version="1.0.0"
)

# Include the other routers 
app.include_router(file_router)
app.include_router(depth_router)


@app.get("/")
async def root():
    return {
        "message": "Hello"
    }

@app.get("/test-db")
async def test_db():
    try:
        with database_engine.connect() as connection:
            return {
                "status": "success", 
                "message": "Database connection successful"
            }
    
    except Exception as e:
        return {
            "status": "error", 
            "message": str(e)
        }