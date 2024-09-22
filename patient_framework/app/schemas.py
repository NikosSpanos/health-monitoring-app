from pydantic import BaseModel
from datetime import datetime

class PatientMessageSchema(BaseModel):
    id: int
    patient_name: str
    message: str
    status_flag: int
    timestamp: datetime

    class Config:
        from_attributes = True

class DeviceSchema(BaseModel):
    device_id: str
    device_type: str
    device_owner: str

    class Config:
        from_attributes = True

class DoctorDeviceMappingSchema(BaseModel):
    device_id: str
    doctor_id: str

    class Config:
        from_attributes = True