from sqlalchemy import Column, Integer, String, Text, DateTime, Boolean, ForeignKey
from sqlalchemy.ext.declarative import declarative_base
from datetime import datetime

Base = declarative_base()

class PatientMessage(Base):
    __tablename__ = 'patient_messages'

    id = Column(Integer, primary_key=True, index=True)
    patient_name = Column(String(100), nullable=False)
    device_owner = Column(String(100), nullable=False)
    message = Column(Text, nullable=False)
    status_flag = Column(Integer, default=0)
    timestamp = Column(DateTime, default=datetime.now())

class Device(Base):
    __tablename__ = 'devices'

    device_id = Column(String(100), primary_key=True)
    device_type = Column(String(100))
    device_owner = Column(String(100), ForeignKey('patient_messages.device_owner'), unique=True)

class DoctorDeviceMapping(Base):
    __tablename__ = 'device_mapping'

    device_id = Column(String(100), ForeignKey('devices.device_id'), primary_key=True)
    doctor_id = Column(String(100)) #doctor's email account

