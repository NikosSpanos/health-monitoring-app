import os
from typing import Dict
class Config:
    SECRET_KEY = os.urandom(24)
    SQLALCHEMY_DATABASE_URI = 'postgresql://admin_user:mypassword@postgres/health_records'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    CELERY_BROKER_URL = 'redis://redis:6380/0'
    CACHE_TYPE = 'RedisCache'
    CACHE_REDIS_HOST = 'redis'
    CACHE_REDIS_PORT = 6379
    CACHE_REDIS_DB = 0
    CACHE_REDIS_URL = 'redis://redis:6379/0'
    CACHE_DEFAULT_TIMEOUT = 100

class HealthConditions:
    def Temperature():
        normal_value = 36.6
        mild_value = 37.5
        critical_value = 38.1
        hypothermi_value = 36.1
        return normal_value, hypothermi_value, mild_value, critical_value
    
    def HeartRate():
        natural_value = 50 #bottom threshold
        mild_value = 120
        critical_value = 150
        return natural_value, mild_value, critical_value
    
    def SpO2():
        natural_value = 95
        mild_value = 90
        critical_value = 85
        return natural_value, mild_value, critical_value

    def Colours():
        critical = "red"
        mild = "yellow"
        hypothermia = "blue"
        normal = "green"
        return critical, mild, hypothermia, normal

    def Messages() -> Dict[str, str]:
        message_text:Dict[str, str] = {}
        message_text["critical_temp"] = "Critical temperature! High probablity of infection!"
        message_text["mild_temp"] = "Mild temperature elevation."
        message_text["hypothermia"] = "Indication of hypothermia"
        message_text["normal_temp"] = "Normal body temperature"
        
        message_text["critical_hr"] = "Critical heart rate!"
        message_text["mild_hr"] = "Mild heart rate elevation."
        message_text["normal_hr"] = "Normal heart rate levels."
        message_text["below_thresh_hr"] = "High drop on heart rate per minute."
        
        message_text["critical_spo2"] = "Critical SpO2 level!"
        message_text["mild_spo2"] =  "Mild SpO2 drop."
        message_text["normal_spo2"] = "Normal SpO2 levels."

        return message_text