from flask import Blueprint, render_template, redirect, url_for, request, session, jsonify
from flask_login import login_user, logout_user, login_required, current_user
from .dataModel import Doctor, Device, DoctorDeviceMapping, DeviceRecords, Owner, MedicalRecords, db
from flask_socketio import join_room, leave_room
from . import login_manager, socketio, thread_lock, redis_client, app, user_threads, stop_signals, user_sessions, patients_session
from flask_caching import Cache
from typing import List, Tuple, Dict
from datetime import datetime, timedelta
from sqlalchemy import func, or_
from config import HealthConditions
import pandas as pd
import json
import math
import threading

main = Blueprint('main', __name__)

@login_manager.user_loader
def load_user(user_id):
    print("USER_ID", user_id)
    # return Doctor.query.filter_by(id = user_id).get(Doctor.email)
    return Doctor.query.get(user_id)

@main.route('/')
def index():
    if 'doctor_id' not in session:
        return redirect(url_for('main.login'))
    return redirect(url_for('main.dashboard'))

@main.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        data:dict = request.get_json()  # Get the JSON data from the fetch request
        if (not data or 'email' not in data) or ('password' not in data):
            return jsonify({'error': 'Invalid input'}), 400
        email = data.get('email')
        password = data.get('password')

        user = Doctor.query.filter_by(email=email).first()
        if user and user.password_hash == password:
            login_user(user)
            # return redirect(url_for('main.dashboard'))
            return jsonify({'email': email}), 200
        else:
            # flash('Invalid email or password!')
            return jsonify({'error': 'Invalid credentials'}), 401
    else:
        return render_template('login.html')

@main.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('main.login'))

# Function to convert string timestamp to datetime
def convert_string_to_datetime(timestamp_str:str):
    return datetime.strptime(timestamp_str, '%Y-%m-%d %H:%M:%S')

# Function to replace Non-Numeric records with None/Null for JavaScript parsing
def clean_graph_data(graph_data):
    # Replace NaN values with None, which translates to null in JSON
    graph_data['y_heart_rate'] = [None if math.isnan(v) else v for v in graph_data['y_heart_rate']]
    graph_data['y_spo2'] = [None if math.isnan(v) else v for v in graph_data['y_spo2']]
    return graph_data

# Master function to compute the relevant KPIs for each patient
def compute_kpis(doctor_email:str, patients:list, redis_conn:Cache, kpi_freshness:int, compute_type:str) -> Dict[str, dict]:

    device_owners:dict = {}
    graphs:dict ={}
    personal_traits:dict ={}
    medical_histories:dict ={}
    avg_temps:dict ={}
    json_blob:dict = {}

    # Set KPI freshness
    freshness = datetime.now() - timedelta(hours=kpi_freshness)
    
    # Retrieve the devices associated to a doctor
    devices:List[Device] = db.session.query(Device).join(DoctorDeviceMapping).filter(DoctorDeviceMapping.doctor_id == doctor_email).all()
    devices = (
        db.session.query(Device)
        .join(Owner, Device.device_owner == Owner.owner_username)
        .join(DoctorDeviceMapping, DoctorDeviceMapping.device_id == Device.device_id)
        .filter(DoctorDeviceMapping.doctor_id == doctor_email)
        .filter(Owner.owner_name.in_(patients))
        .all()
    )
    for device in devices:
        device_data:List[DeviceRecords] = DeviceRecords.query.filter_by(
            device_id=device.device_id # Devices belonging to a doctor
        ).filter(
            func.to_timestamp(DeviceRecords.timestamp, 'YYYY-MM-DD HH24:MI:SS') >= freshness
        ).all()
        # Plot KPI
        # =================
        data = {
            'Timestamp': [convert_string_to_datetime(record.timestamp) for record in device_data],
            'Heart Rate': [record.heart_rate for record in device_data],
            'SpO2': [record.spo2 for record in device_data],
            'Temperature': [record.temperature if record.temperature else -1.0 for record in device_data]
        }
        df = pd.DataFrame(data)
        df['Timestamp'] = pd.to_datetime(df['Timestamp'])
        df.set_index('Timestamp', inplace=True)
        df_resampled = df.resample('2min').mean()

        if compute_type == "refresh":
            graph_data = {
                'x': df_resampled.index.strftime('%Y-%m-%dT%H:%M:%S').tolist(),
                'y_heart_rate': df_resampled['Heart Rate'].tolist(),
                'y_spo2': df_resampled['SpO2'].tolist(),
                'device_owner': device.device_owner
            }
            # Clean the data before sending
            graph_data = clean_graph_data(graph_data)
            graphs[device.device_owner] = json.dumps(graph_data)
        else:
            graph_data = {
                'x': [],
                'y_heart_rate': [],
                'y_spo2': [],
                'device_owner': device.device_owner
            }
            graphs[device.device_owner] = json.dumps(graph_data)
        # Body temperature KPI
        # =====================
        # avg_temp = get_avg_temperature(device.device_id)
        if len(data['Temperature']) > 0:
            avg_temp = round(sum(data['Temperature']) / len(data['Temperature']), 2)
        else:
            avg_temp = -1.0
        avg_temps[device.device_owner] = float(avg_temp) # Log Patient's body temperature to JSON Blob object

        # Patient's personal metadata
        # ============================
        owner:Owner = Owner.query.filter_by(owner_username=device.device_owner).first()
        personal_traits[device.device_owner] = {
            'name': owner.owner_name,
            'age': owner.age,
            'gender': owner.gender
        } # Log Patient's personal metadata to JSON Blob object

        # Patient's Medical history
        # ===========================
        medical_history:MedicalRecords = MedicalRecords.query.filter_by(medical_history_record_id=owner.medical_history_record_id).first()
        medical_histories[device.device_owner] = {
            'chronic_conditions': medical_history.chronic_conditions,
            'family_history': medical_history.family_history,
            'smoking': medical_history.smoking,
            'alcohol_usage': medical_history.alcohol_usage,
            'allergies': medical_history.allerges,
            'medication': medical_history.medication
        } # Log Patient's medical metadata to JSON Blob object

        # Append device owner
        device_owners[device.device_owner] = owner.owner_name

        redis_conn.set(
            device.device_owner,
            {
                'device_owners': device_owners[device.device_owner],
                'graphs': graphs[device.device_owner],
                'personal_traits': personal_traits[device.device_owner],
                'medical_histories': medical_histories[device.device_owner],
                'avg_temps': avg_temps[device.device_owner]
            }
        )

    json_blob:Dict[str, dict] = {
        'device_owners': device_owners,
        'graphs': graphs,
        'personal_traits': personal_traits,
        'medical_histories': medical_histories,
        'avg_temps': avg_temps
    }
    return json_blob

def background_thread(doctor_email:str, patients:list):
    while not stop_signals[doctor_email].is_set():
        with app.app_context():
            computed_records = compute_kpis(doctor_email, patients, redis_client, 2, "refresh")
            for id, name in computed_records['device_owners'].items():
                socketio.emit(
                    'update_patient_data',
                    {
                        'device_owner': id,
                        'avg_temp': computed_records['avg_temps'][id],
                        'graph_data': computed_records['graphs'][id],
                        'personal_traits': computed_records['personal_traits'][id],
                        'medical_history': computed_records['medical_histories'][id]
                    },
                    room=doctor_email
                )
            socketio.sleep(5)
    print(f"Background thread for {doctor_email} has been stopped.")

def monitor_critical_condition(doctor_email:str):
    temp_normal, temp_hypothermi, temp_mild, temp_critical = HealthConditions.Temperature()
    hr_natural, hr_mild, hr_critical = HealthConditions.HeartRate()
    spo2_natural, spo2_mild, spo2_critical = HealthConditions.SpO2()
    critical, mild, hypothermia, normal = HealthConditions.Colours()
    
    messages = HealthConditions.Messages()
    
    while not stop_signals[doctor_email].is_set():
        with app.app_context():
            freshness = datetime.now() - timedelta(minutes=1)
            devices:List[Device] = (
                db.session.query(Device)
                .join(DoctorDeviceMapping, Device.device_id == DoctorDeviceMapping.device_id)
                .join(DeviceRecords, Device.device_id == DeviceRecords.device_id)
                .filter(DoctorDeviceMapping.doctor_id == doctor_email)
                .filter(
                    (func.to_timestamp(DeviceRecords.timestamp, 'YYYY-MM-DD HH24:MI:SS') >= freshness) &
                    (
                        or_(
                            DeviceRecords.temperature < temp_hypothermi,
                            DeviceRecords.temperature > temp_mild,
                            DeviceRecords.heart_rate >= hr_mild,
                            DeviceRecords.spo2 <= spo2_mild
                        )
                    )
                )
                .all()
            )

            if devices:
                for device in devices:
                    device_data:List[DeviceRecords] = DeviceRecords.query.filter_by(
                        device_id=device.device_id
                    ).filter(
                        func.to_timestamp(DeviceRecords.timestamp, 'YYYY-MM-DD HH24:MI:SS') >= freshness
                    ).all()
                    owner:Owner = Owner.query.filter_by(owner_username=device.device_owner).first()
                    temperatures = [ record.temperature if record.temperature is not None else -1.0 for record in device_data ]
                    heart_rates = [ record.heart_rate if record.heart_rate is not None else -1.0 for record in device_data ]
                    spo2s = [ record.spo2 if record.spo2 is not None else -1.0 for record in device_data ]

                    temperature = float(round(sum(temperatures) / len(temperatures), 2) if temperatures else -1.0)
                    heart_rate = float(round(sum(heart_rates) / len(heart_rates), 2) if heart_rates else -1.0)
                    spo2 = float(round(sum(spo2s) / len(spo2s), 2) if spo2s else -1.0)

                    mapping_conditions = {
                        'critical_temp': temperature >= temp_critical,
                        'mild_temp': (temperature >= temp_mild) and (temperature < temp_critical),
                        'hypothermia': (temperature < temp_hypothermi),
                        'normal_temp': (temperature >= temp_hypothermi) and (temperature <= temp_normal),
                        'critical_hr': heart_rate >= hr_critical,
                        'mild_hr': (heart_rate >= hr_mild) and (heart_rate < hr_critical),
                        'normal_hr': (heart_rate > hr_natural) and (heart_rate < hr_mild),
                        'critical_spo2': spo2 <= spo2_critical,
                        'mild_spo2': (spo2 > spo2_critical) and (spo2 <= spo2_mild),
                        'normal_spo2': (heart_rate > spo2_mild),
                    }

                    # Emit the general KPI data (for the circle widget to update colors)
                    socketio.emit('patient_notification', {
                        'device_owner': owner.owner_name,
                        'temperature_metadata': {
                            "value": temperature,
                            "color":
                                critical if mapping_conditions['critical_temp'] else 
                                mild if mapping_conditions['mild_temp'] else 
                                hypothermia if mapping_conditions['hypothermia'] else 
                                normal,
                            "message":
                                messages['critical_temp'] if mapping_conditions['critical_temp'] else
                                messages['mild_temp'] if mapping_conditions['mild_temp'] else
                                messages['hypothermia'] if mapping_conditions['hypothermia'] else
                                messages['normal_temp']
                        },
                        'heartrate_metadata': {
                            "value": heart_rate,
                            "color":
                                critical if (mapping_conditions['critical_hr']) or (heart_rate < hr_natural) else
                                mild if mapping_conditions['mild_hr'] else
                                normal,
                            "message":
                                messages['critical_hr'] if mapping_conditions['critical_hr'] else
                                messages['mild_hr'] if mapping_conditions['mild_hr'] else
                                messages['below_thresh_hr'] if heart_rate < hr_natural else
                                messages['normal_hr']
                        },
                        'spo2_metadata': {
                            "value": spo2,
                            "color": 
                                critical if mapping_conditions['critical_spo2'] else
                                mild if mapping_conditions['mild_spo2'] else
                                normal,
                            "message":
                                messages['critical_spo2'] if mapping_conditions['critical_spo2'] else
                                messages['mild_spo2'] if mapping_conditions['mild_spo2'] else
                                messages['normal_spo2']
                        }
                    }, room=doctor_email)
            socketio.sleep(15)

def get_notifications_info(email:str) -> str:
    doctor_info:Doctor = db.session.query(Doctor).filter(Doctor.email == email).first()
    print(doctor_info)
    target_name:str = doctor_info.name
    return target_name

def fetch_patients(email:str) -> List[str]:
    owner_names = (
        db.session.query(Owner.owner_name)
        .join(Device, Owner.owner_username == Device.device_owner)
        .join(DoctorDeviceMapping, DoctorDeviceMapping.device_id == Device.device_id)
        .filter(DoctorDeviceMapping.doctor_id == email)
        .all()
    )
    owner_names:List[str] = [name for (name,) in owner_names]
    return owner_names

@main.route('/dashboard')
@login_required
def dashboard():
    patient_names = fetch_patients(current_user.email)
    return render_template(
        'dashboard.html',
        patients=patient_names
    )

@main.route('/notification')
@login_required
def notification():
    email = current_user.email
    doctor_name = get_notifications_info(email)
    return render_template('notification.html', message="No critical conditions found", doctor_name = doctor_name)

@socketio.on('get_patient_data')
def handle_patients(data:Dict[str, str]):
    global user_threads, stop_signals, patients_session
    with thread_lock:
        if current_user.is_authenticated:
            sid = request.sid
            email = data.get('email')
            patients = data.get('patients')

            user_sessions[email] = sid
            join_room(email, sid=sid)

            if email not in stop_signals:
                stop_signals[email] = threading.Event()
            else:
                stop_signals[email].clear()

            if email and patients:
                if email in user_threads:
                    print(f"user_threads[{email}] is of type {type(user_threads[email])}")
                    if patients != patients_session[sid]:
                        del user_threads[email]
                        del patients_session[sid]
                        user_threads[email] = socketio.start_background_task(background_thread, email, patients)
                else:
                    # if (email not in user_threads) or (not user_threads[email].is_alive()):
                    if (email not in user_threads):
                        patients_session[sid] = patients
                        user_threads[email] = socketio.start_background_task(background_thread, email, patients)
                    else:
                        print("No patients selected or missing email.")
        else:
            print("User is not authenticated. Background thread will not start yet.")

@socketio.on('user_info')
def handle_connect(data:Dict[str, str]):
    global user_threads, stop_signals
    with thread_lock:
        if current_user.is_authenticated:
            sid = request.sid
            email = data.get('email')
            page = data.get('page')

            user_sessions[email] = sid
            join_room(email, sid=sid)

            if email not in stop_signals:
                stop_signals[email] = threading.Event()
            else:
                stop_signals[email].clear()

            # if page == '/dashboard':
            #     if (email not in user_threads) or (not user_threads[email]['monitor_patient'].is_alive()):
            #         user_threads[email]['monitor_patient'] = socketio.start_background_task(background_thread, email)

            # elif page == '/notification':
            #     if (email not in user_threads) or (not user_threads[email]['critical_conditions'].is_alive()):
            #         user_threads[email]['critical_conditions'] = socketio.start_background_task(monitor_critical_condition, email)
            
            # if page == '/dashboard':
            #     if (email not in user_threads) or (not user_threads[email].is_alive()):
            #         user_threads[email] = socketio.start_background_task(background_thread, email)

            if page == '/notification':
                if (email not in user_threads) or (not user_threads[email].is_alive()):
                    user_threads[email] = socketio.start_background_task(monitor_critical_condition, email)
            else:
                print("Received message from invalid client. Please check the rendering page.")
        else:
            print("User is not authenticated. Background thread will not start yet.")

@socketio.event
def disconnect():
    global user_threads, stop_signals
    email = request.args.get('email')
    sid = request.sid
    
    if email in user_sessions and user_sessions[email] == sid:
        leave_room(email, sid=sid)
        del user_sessions[email]

    if email in stop_signals:
        stop_signals[email].set()

    with thread_lock:
        if email in user_threads:
            del user_threads[email]
        if email in stop_signals:
            del stop_signals[email]

@socketio.on('rejoin')
def handle_rejoin(data:dict):
    email = data.get('email')
    sid = request.sid
    page = data.get('page')

    if email:
        user_sessions[email] = sid
        join_room(email, sid=sid)
        
        # Optionally restart or verify background thread here
        with thread_lock:
            if page == '/dashboard':
                if (email not in user_threads) or (not user_threads[email]['monitor_patient'].is_alive()):
                    user_threads[email]['monitor_patient'] = socketio.start_background_task(background_thread, email)

            elif page == '/notification':
                if (email not in user_threads) or (not user_threads[email]['critical_conditions'].is_alive()):
                    user_threads[email]['critical_conditions'] = socketio.start_background_task(monitor_critical_condition, email)

@socketio.on('server_response')
def handle_connect():
    print('Client connected')
    print(current_user.email)
    email = request.args.get('email')
    print(email)
    # Once connected, emit a message to the client
    # socketio.emit('server_response', {'data': 'Connected to server'}, room=str(current_user.email))
    if email:
        print(f'Client connected with email: {email}')
        # Store the user's session ID mapped to their email
        user_sessions[email] = request.sid
        # Add the user to their own room (identified by their email)
        join_room(email, sid = user_sessions[email])
        # Emit a response to the client to confirm connection
        socketio.emit('server_response', {'data': 'Connected to server'}, room=email)
    else:
        print('Email not found in connection request.')

