from . import socketio, celery, db
from .dataModel import DeviceRecords, Device, DoctorDeviceMapping
from datetime import datetime
from celery.result import AsyncResult
from flask_socketio import emit

@celery.task
def compute_kpi(device_id):
    data = DeviceRecords.query.filter_by(device_id=device_id).all()
    avg_heartrate = sum(d.heart_rate for d in data) / len(data) if data else 0
    avg_spo2 = sum(d.spo2 for d in data) / len(data) if data else 0
    return {
        'device_id': device_id,
        'avg_heartrate': avg_heartrate,
        'avg_spo2': avg_spo2
    }

@celery.task(bind=True)
def compute_heartRate_per_minute(self, doctor_id):
    devices = db.session.query(Device.device_id, Device.device_type).join(DoctorDeviceMapping).filter(DoctorDeviceMapping.doctor_id == doctor_id).all()

    kpi_results = []
    for device_id, device_type in devices:
        raw_data = db.session.query(DeviceRecords).filter(DeviceRecords.device_id == device_id).all()

        data = [
            {
                'timestamp': datetime.strptime(d.timestamp, '%Y-%m-%d %H:%M:%S'),  # Adjust format as necessary
                'heartrate': d.heart_rate
            }
            for d in raw_data
        ]

        # Calculate average heart rate per minute
        grouped_data = {}
        for entry in data:
            minute = entry['timestamp'].replace(second=0, microsecond=0)
            if minute not in grouped_data:
                grouped_data[minute] = {'heartrate_sum': 0, 'count': 0}
            grouped_data[minute]['heartrate_sum'] += entry['heartrate']
            grouped_data[minute]['count'] += 1
        
        avg_heart_rate = [
            {'minute': minute, 'avg_heartrate': values['heartrate_sum'] / values['count']}
            for minute, values in grouped_data.items()
        ]

        # Structure the result for the device
        device_kpi = {
            'device_id': device_id,
            'device_type': device_type,
            'avg_heart_rate_per_minute': [
                {
                    'minute': kpi['minute'].strftime('%Y-%m-%d %H:%M'),
                    'avg_heartrate': kpi['avg_heartrate']
                }
                for kpi in avg_heart_rate
            ]
        }

        # Append the device KPI result to the overall list
        kpi_results.append(device_kpi)
    
    # Emit the result once completed
    socketio.emit('kpi_data', kpi_results, room=self.request.id)

@socketio.on('check_task_status')
def check_task_status(task_id):
    result = AsyncResult(task_id)
    if result.ready():
        # Emit the result back to the client
        emit('kpi_data', result.result)
    else:
        emit('task_status', {'status': 'Pending'})