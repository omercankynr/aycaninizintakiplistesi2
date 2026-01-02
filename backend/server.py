from fastapi import FastAPI, APIRouter, HTTPException
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
import os
import logging
from pathlib import Path
from pydantic import BaseModel, Field, ConfigDict
from typing import List, Optional
import uuid
from datetime import datetime, timezone, date
from enum import Enum

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

# MongoDB connection
mongo_url = os.environ['MONGO_URL']
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ['DB_NAME']]

# Create the main app without a prefix
app = FastAPI()

# Create a router with the /api prefix
api_router = APIRouter(prefix="/api")

# Employee list with colors
EMPLOYEES = [
    {"id": "ayca_cisem", "name": "AYÇA ÇİSEM ÇOBAN", "short_name": "AYÇA Ç.", "role": "TL", "color": "#E91E63"},
    {"id": "enis", "name": "ENİS USLU", "short_name": "ENİS U.", "role": "TL", "color": "#2196F3"},
    {"id": "onur", "name": "ONUR KARAGÜLER", "short_name": "ONUR K.", "role": "TL", "color": "#FF5722"},
    {"id": "busra", "name": "BÜŞRA PARILTI", "short_name": "BÜŞRA P.", "role": "Agent", "color": "#9C27B0"},
    {"id": "sila", "name": "SILA USTA", "short_name": "SILA U.", "role": "Agent", "color": "#00BCD4"},
    {"id": "nergiz", "name": "NERGİZ OZĞAN", "short_name": "NERGİZ O.", "role": "Agent", "color": "#4CAF50"},
    {"id": "aysun", "name": "AYSUN KUL", "short_name": "AYSUN K.", "role": "Agent", "color": "#CDDC39"},
    {"id": "elif", "name": "ELİF ERKAN", "short_name": "ELİF E.", "role": "Agent", "color": "#FF9800"},
    {"id": "ebru", "name": "EBRU FİDAN", "short_name": "EBRU F.", "role": "Agent", "color": "#795548"},
    {"id": "ayca_demir", "name": "AYÇA DEMİR", "short_name": "AYÇA D.", "role": "Agent", "color": "#607D8B"},
    {"id": "kader", "name": "KADER MÜREN", "short_name": "KADER M.", "role": "Agent", "color": "#F44336"},
    {"id": "rabia", "name": "RABİA BATUK", "short_name": "RABİA B.", "role": "Agent", "color": "#673AB7"}
]

# Define Models
class LeaveEntry(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    employee_id: str
    date: str  # YYYY-MM-DD format
    week_start: str  # Week start date for grouping
    slot: int  # 0-6 slot position
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

class LeaveEntryCreate(BaseModel):
    employee_id: str
    date: str
    week_start: str
    slot: int

class LeaveEntryDelete(BaseModel):
    employee_id: str
    date: str

class OvertimeEntry(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    employee_id: str
    date: str  # YYYY-MM-DD format
    hours: float
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

class OvertimeEntryCreate(BaseModel):
    employee_id: str
    date: str
    hours: float

class LeaveTypeEnum(str, Enum):
    UNPAID = "unpaid"  # Ücretsiz izin
    ANNUAL = "annual"  # Yıllık izin
    COMPENSATORY = "compensatory"  # Telafi izni

class LeaveTypeEntry(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    employee_id: str
    date: str  # YYYY-MM-DD format
    leave_type: LeaveTypeEnum
    hours: Optional[float] = None  # Only for compensatory leave
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

class LeaveTypeEntryCreate(BaseModel):
    employee_id: str
    date: str
    leave_type: LeaveTypeEnum
    hours: Optional[float] = None

# Endpoints
@api_router.get("/")
async def root():
    return {"message": "İzin Yönetim Sistemi API"}

@api_router.get("/employees")
async def get_employees():
    return EMPLOYEES

# Leave Entry Endpoints
@api_router.post("/leaves", response_model=LeaveEntry)
async def create_leave_entry(input: LeaveEntryCreate):
    # Validate employee
    if not any(e["id"] == input.employee_id for e in EMPLOYEES):
        raise HTTPException(status_code=400, detail="Geçersiz çalışan ID")
    
    # Check validation rules
    today = datetime.now().strftime("%Y-%m-%d")
    if input.date == today:
        raise HTTPException(status_code=400, detail="Bugün için izin kullanımı yasaktır")
    
    # Check if Rabia and Ayça Demir conflict
    if input.employee_id in ["rabia", "ayca_demir"]:
        other_id = "ayca_demir" if input.employee_id == "rabia" else "rabia"
        existing = await db.leaves.find_one({"employee_id": other_id, "date": input.date})
        if existing:
            raise HTTPException(status_code=400, detail="Rabia Batuk ve Ayça Demir aynı gün izinli olamaz")
    
    # Check slot limit for the day
    existing_slots = await db.leaves.count_documents({"date": input.date})
    
    # Check if Ayça Çisem is on leave that day
    ayca_cisem_leave = await db.leaves.find_one({"employee_id": "ayca_cisem", "date": input.date})
    max_slots = 3 if ayca_cisem_leave else 7
    
    if existing_slots >= max_slots:
        raise HTTPException(status_code=400, detail=f"Bu gün için maksimum izin sayısına ({max_slots}) ulaşıldı")
    
    # Check if employee already has leave on this date
    existing_leave = await db.leaves.find_one({"employee_id": input.employee_id, "date": input.date})
    if existing_leave:
        raise HTTPException(status_code=400, detail="Bu çalışan bu tarihte zaten izinli")
    
    leave_obj = LeaveEntry(**input.model_dump())
    doc = leave_obj.model_dump()
    doc['created_at'] = doc['created_at'].isoformat()
    
    await db.leaves.insert_one(doc)
    return leave_obj

@api_router.get("/leaves")
async def get_leaves(week_start: Optional[str] = None):
    query = {}
    if week_start:
        query["week_start"] = week_start
    leaves = await db.leaves.find(query, {"_id": 0}).to_list(1000)
    return leaves

@api_router.delete("/leaves/{leave_id}")
async def delete_leave(leave_id: str):
    result = await db.leaves.delete_one({"id": leave_id})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="İzin kaydı bulunamadı")
    return {"message": "İzin silindi"}

@api_router.delete("/leaves")
async def delete_leave_by_criteria(employee_id: str, date: str):
    result = await db.leaves.delete_one({"employee_id": employee_id, "date": date})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="İzin kaydı bulunamadı")
    return {"message": "İzin silindi"}

# Overtime Endpoints
@api_router.post("/overtime", response_model=OvertimeEntry)
async def create_overtime_entry(input: OvertimeEntryCreate):
    if not any(e["id"] == input.employee_id for e in EMPLOYEES):
        raise HTTPException(status_code=400, detail="Geçersiz çalışan ID")
    
    overtime_obj = OvertimeEntry(**input.model_dump())
    doc = overtime_obj.model_dump()
    doc['created_at'] = doc['created_at'].isoformat()
    
    await db.overtime.insert_one(doc)
    return overtime_obj

@api_router.get("/overtime")
async def get_overtime():
    overtime_list = await db.overtime.find({}, {"_id": 0}).to_list(1000)
    return overtime_list

@api_router.delete("/overtime/{overtime_id}")
async def delete_overtime(overtime_id: str):
    result = await db.overtime.delete_one({"id": overtime_id})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Fazla çalışma kaydı bulunamadı")
    return {"message": "Fazla çalışma silindi"}

# Leave Type Endpoints
@api_router.post("/leave-types", response_model=LeaveTypeEntry)
async def create_leave_type_entry(input: LeaveTypeEntryCreate):
    if not any(e["id"] == input.employee_id for e in EMPLOYEES):
        raise HTTPException(status_code=400, detail="Geçersiz çalışan ID")
    
    if input.leave_type == LeaveTypeEnum.COMPENSATORY and not input.hours:
        raise HTTPException(status_code=400, detail="Telafi izni için saat belirtilmeli")
    
    leave_type_obj = LeaveTypeEntry(**input.model_dump())
    doc = leave_type_obj.model_dump()
    doc['created_at'] = doc['created_at'].isoformat()
    
    await db.leave_types.insert_one(doc)
    return leave_type_obj

@api_router.get("/leave-types")
async def get_leave_types():
    leave_types = await db.leave_types.find({}, {"_id": 0}).to_list(1000)
    return leave_types

@api_router.delete("/leave-types/{leave_type_id}")
async def delete_leave_type(leave_type_id: str):
    result = await db.leave_types.delete_one({"id": leave_type_id})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="İzin türü kaydı bulunamadı")
    return {"message": "İzin türü silindi"}

# Include the router in the main app
app.include_router(api_router)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=os.environ.get('CORS_ORIGINS', '*').split(','),
    allow_methods=["*"],
    allow_headers=["*"],
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

@app.on_event("shutdown")
async def shutdown_db_client():
    client.close()
