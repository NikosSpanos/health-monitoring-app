from . import db
from flask_login import UserMixin

class Doctor(UserMixin, db.Model):
    __tablename__ = 'doctors'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100))
    email = db.Column(db.String(100), unique=True)
    password_hash = db.Column(db.String(100))

class Device(db.Model):
    __tablename__ = 'devices'
    device_id = db.Column(db.String(100), primary_key=True)
    device_type = db.Column(db.String(100))
    device_owner = db.Column(db.String(100),db.ForeignKey('owners.owner_username'), unique=True)

class DoctorDeviceMapping(db.Model):
    __tablename__ = 'device_mapping'
    device_id = db.Column(db.String(100), db.ForeignKey('devices.device_id'), primary_key=True)
    doctor_id = db.Column(db.String(100), db.ForeignKey('doctors.email'))

class MedicalRecords(db.Model):
    __tablename__ = 'medical_records'
    medical_history_record_id = db.Column(db.Integer, primary_key=True)
    illnesses = db.Column(db.String(100))
    surgeries = db.Column(db.String(100))
    chronic_conditions = db.Column(db.String(200))
    family_history = db.Column(db.String(200))
    smoking = db.Column(db.String(5))
    alcohol_usage = db.Column(db.String(15))
    allerges = db.Column(db.String(200))
    medication = db.Column(db.String(200))

class Owner(db.Model):
    __tablename__ = 'owners'
    owner_username = db.Column(db.String(100), primary_key=True)
    owner_name = db.Column(db.String(100))
    age = db.Column(db.Integer)
    marital_status = db.Column(db.String(50))
    gender = db.Column(db.String(50))
    medical_history_record_id = db.Column(db.Integer, db.ForeignKey('medical_records.medical_history_record_id'))

class DeviceRecords(db.Model):
    __tablename__ = 'health_data_records'
    id = db.Column(db.Integer, primary_key=True)
    device_id = db.Column(db.String(50), db.ForeignKey('devices.device_id'))
    heart_rate = db.Column(db.Integer)
    temperature = db.Column(db.Numeric(precision=10, scale=2), nullable=False)
    spo2 = db.Column(db.Integer)
    timestamp = db.Column(db.String(20))