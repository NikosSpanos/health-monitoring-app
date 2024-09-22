import os
class Config:
    SECRET_KEY = os.urandom(24)
    SQLALCHEMY_DATABASE_URI:str = 'postgresql://admin_user:mypassword@postgres/health_records'
    SQLALCHEMY_TRACK_MODIFICATIONS = False