from flask import Blueprint, render_template, redirect, url_for, request, session, jsonify
from flask_login import login_user, logout_user, login_required, current_user
from .dataModel import Doctor, Device, DoctorDeviceMapping, DeviceRecords, Owner, MedicalRecords, PatientMessage, db
from flask_socketio import join_room, leave_room
from . import login_manager, socketio, thread_lock, redis_client, app, user_threads, stop_signals, user_sessions, patients_session, logger
from flask_caching import Cache
from typing import List, Dict
from datetime import datetime, timedelta
from sqlalchemy import func, or_, distinct, and_
from config import HealthConditions
import pandas as pd
import json
import math
import threading

main = Blueprint('main', __name__, url_prefix='/')

@login_manager.user_loader
def load_user(user_id):
    # return Doctor.query.filter_by(id = user_id).get(Doctor.email)
    return Doctor.query.get(user_id)

def safe_delete(dictionary, key):
    """Safely delete a key from a dictionary if it exists."""
    with thread_lock:
        if key in dictionary:
            del dictionary[key]

def stop_user_thread(email):
    """Safely stop and remove a user's background thread."""
    with thread_lock:
        if email in stop_signals:
            stop_signals[email].set()
        if email in user_threads:
            user_threads[email].join(timeout=5)  # Wait for thread to finish
            safe_delete(user_threads, email)
        safe_delete(stop_signals, email)

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
    email = request.form.get('email')

    # Gracefully stop background threads and clean up resources
    if email in stop_signals:
        stop_signals[email].set()
    
    with thread_lock:
        user_threads.pop(email, None)
        stop_signals.pop(email, None)
        user_sessions.pop(email, None)
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
def compute_kpis(doctor_email:str, patients:list, patient_usernames:list, redis_conn:Cache, kpi_freshness:int) -> Dict[str, dict]:

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
        .filter(
            and_(
                Owner.owner_name.in_(patients),
                Owner.owner_username.in_(patient_usernames)
            ) #+add only the selected useername from User_id split
        )
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
            'Temperature': [record.temperature for record in device_data]
        }
        df = pd.DataFrame(data)
        df['Timestamp'] = pd.to_datetime(df['Timestamp'])
        df.set_index('Timestamp', inplace=True)
        df_resampled = df.resample('2min').mean()

        # if compute_type == "refresh":
        graph_data = {
            'x': df_resampled.index.strftime('%Y-%m-%dT%H:%M:%S').tolist(),
            'y_heart_rate': df_resampled['Heart Rate'].tolist(),
            'y_spo2': df_resampled['SpO2'].tolist(),
            'device_owner': device.device_owner
        }
        # Clean the data before sending
        graph_data = clean_graph_data(graph_data)
        graphs[device.device_owner] = json.dumps(graph_data)
        # else:
        #     graph_data = {
        #         'x': [],
        #         'y_heart_rate': [],
        #         'y_spo2': [],
        #         'device_owner': device.device_owner
        #     }
        #     graphs[device.device_owner] = json.dumps(graph_data)
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

# Valid option without bugs for backgorund_thread
# def background_thread(doctor_email:str, patients:list):
#     global stop_signals

#     if not stop_signals[doctor_email]:
#         logger.info(f"No stop signal for {doctor_email}, exiting thread.")
#         return
#     try:
#         while not stop_signals[doctor_email].is_set():
#             with app.app_context():
#                 computed_records = compute_kpis(doctor_email, patients, redis_client, 2)
#                 for id, name in computed_records['device_owners'].items():
#                     logger.info(f"Emitting patient data for {name} with ID {id} to room {doctor_email}")
#                     socketio.emit(
#                         'update_patient_data',
#                         {
#                             'device_owner': id,
#                             'avg_temp': computed_records['avg_temps'][id],
#                             'graph_data': computed_records['graphs'][id],
#                             'personal_traits': computed_records['personal_traits'][id],
#                             'medical_history': computed_records['medical_histories'][id]
#                         },
#                         room=doctor_email
#                     )
#                 socketio.sleep(10)
#     except Exception as e:
#         logger.info(f"Error in background thread for {doctor_email}: {str(e)}")
#     finally:
#         logger.info(f"Background thread for {doctor_email} stopped.")


def reverse_engineer_names(concatenated_value:str):
    # Split the concatenated string by underscores
    parts:list = concatenated_value.split('_')
    
    # Extract the original name (all parts except the last one, which is the username)
    name_parts:List[str] = parts[:-1]

    # Reconstruct the original name by capitalizing the first letter of each word
    original_name = ' '.join([part.capitalize() for part in name_parts])
    
    return original_name

def reverse_engineer_username(concatenated_value:str):
    parts:list = concatenated_value.split('_')
    username_part = parts[-1]

    return username_part


def background_thread(doctor_email: str):
    global stop_signals, patients_session

    if not stop_signals[doctor_email]:
        logger.info(f"No stop signal for {doctor_email}, exiting thread.")
        return

    try:
        while not stop_signals[doctor_email].is_set():
            logger.info(f"Fetching data for {doctor_email}")

            # Fetch the latest patient list dynamically from patients_session
            patients = patients_session.get(doctor_email, [])
            if not patients:
                logger.info(f"No patients for {doctor_email}, waiting for updates")
                socketio.sleep(5)
                continue  # If no patients, wait for updates
            
            patients_names:list = [reverse_engineer_names(value) for value in patients]
            patients_usernames:list = [reverse_engineer_username(value) for value in patients]
            assert len(patients_names) == len(patients_usernames)
            logger.info(f"Fetching names for patients: {patients_names}")
            logger.info(f"Fetching usernames for patients: {patients_usernames}")
            with app.app_context():
                computed_records = compute_kpis(doctor_email, patients_names, patients_usernames, redis_client, 2)
                for id, name in computed_records['device_owners'].items():
                    logger.info(f"Emitting data for patient {name} (ID: {id})")
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
            # Sleep for 5 seconds before fetching data again
            socketio.sleep(5)
    except Exception as e:
        logger.error(f"Error in background thread for {doctor_email}: {str(e)}")
    finally:
        logger.info(f"Background thread for {doctor_email} stopped.")

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
    target_name:str = doctor_info.name
    return target_name

def normalize_name(name:str):
    return name.lower().replace(" ", "_")

def fetch_patients(doctor_email:str):
    try:
        owner_names_usernames = (
            db.session.query(distinct(Owner.owner_name), Owner.owner_username)
            .join(Device, Owner.owner_username == Device.device_owner)
            .join(DoctorDeviceMapping, Device.device_id == DoctorDeviceMapping.device_id)
            .filter(DoctorDeviceMapping.doctor_id == doctor_email)
            .all()
        )
        
        # Extract names from the result tuples
        # return ([name[0] for name in owner_names], )
        owner_names = [result[0] for result in owner_names_usernames]
        owner_usernames:List[str] = [result[1] for result in owner_names_usernames]

        # Merge the lists with normalized names and usernames
        merged_list = [f"{normalize_name(name)}_{username.lower()}" for name, username in zip(owner_names, owner_usernames)]

        return merged_list
    
    except Exception as e:
        # Log the error
        logger.error(f"Error fetching patients for doctor {doctor_email}: {str(e)}")
        # Re-raise the exception to be handled by the calling function
        raise

# @main.route('/patients', methods=['POST'])
# @login_required
# def get_patients():
#     if request.method == 'POST':
#         # Assuming the doctor is logged in, use current_user.email
#         data:dict = request.get_json()
#         if (not data or 'email' not in data):
#             return jsonify({'error': 'Invalid input'}), 400
#         email = data.get('email')
#         print(email)
    
#     # Fetch patient names associated with the doctor's email
#     owner_names = fetch_patients(email)
#     print(owner_names)

#     return jsonify({"patients": owner_names}), 200

@main.route('/patients', methods=['POST'])
@login_required
def get_patients():
    try:
        data = request.get_json()
        logger.info("My email is: " + str(data))
        
        if not data or 'email' not in data:
            return jsonify({'error': 'Invalid input'}), 400
        
        email = data['email']
        
        # Verify that the email matches the logged-in user's email
        if email != current_user.email:
            return jsonify({'error': 'Unauthorized access'}), 403
        
        # Fetch patient names associated with the doctor's email
        owner_names = fetch_patients(email)
        logger.info(owner_names)
        
        if not owner_names:
            return jsonify({'patients': []}), 200
        
        return jsonify({'patients': owner_names}), 200
    
    except Exception as e:
        logger.info(f"Error in get_patients: {str(e)}")
        return jsonify({'error': 'Internal server error'}), 500

@main.route('/dashboard')
@login_required
def dashboard():
    patient_names = fetch_patients(current_user.email)
    logger.info(patient_names)
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

# @socketio.on('get_patient_data')
# def handle_patients(data:Dict[str, str]):
#     global user_threads, stop_signals, patients_session
#     with thread_lock:
#         if current_user.is_authenticated:
#             sid = request.sid
#             email = data.get('email')
#             patients = data.get('patients')

#             user_sessions[email] = sid
#             join_room(email, sid=sid)

#             if email not in stop_signals:
#                 stop_signals[email] = threading.Event()
#             else:
#                 stop_signals[email].clear()

#             if email and patients:
#                 if email in user_threads:
#                     # print(f"user_threads[{email}] is of type {type(user_threads[email])}")
#                     logger.info(f"user_threads[{email}] is of type {type(user_threads[email])}")
#                     if patients != patients_session[sid]:
#                         del user_threads[email]
#                         del patients_session[sid]
#                         user_threads[email] = socketio.start_background_task(background_thread, email, patients)
#                 else:
#                     if (email not in user_threads):
#                         patients_session[sid] = patients
#                         user_threads[email] = socketio.start_background_task(background_thread, email, patients)
#                     else:
#                         print("No patients selected or missing email.")
#         else:
#             print("User is not authenticated. Background thread will not start yet.")

# @socketio.on('get_patient_data')
# @login_required
# def handle_patients(data:dict):
#     global user_threads, stop_signals, patients_session
#     with thread_lock:
#         if current_user.is_authenticated:
#             sid = request.sid
#             email:str = data.get('email')
#             patients:list = data.get('patients')

#             user_sessions[email] = sid
#             join_room(email, sid=sid)

#             if email not in stop_signals:
#                 stop_signals[email] = threading.Event()
#             else:
#                 stop_signals[email].clear()

#             if email and patients:
#                 # Only restart the background thread if the patient selection has changed
#                 if email in user_threads:
#                     logger.info(patients)
#                     logger.info(patients_session.get(sid))
#                     if patients != patients_session.get(sid,[]):
#                         # The patients list has changed, restart the background thread
#                         logger.info(f"Restarting thread for {email} due to patient change")
#                         stop_signals[email].set()  # Stop the old thread
#                         del user_threads[email]
#                         del patients_session[sid]
#                         patients_session[sid] = patients
#                         user_threads[email] = socketio.start_background_task(background_thread, email, patients)
#                     else:
#                         logger.info(f"Thread for {email} is already running with the same patients.")
#                         with app.app_context():
#                             computed_records = compute_kpis(email, patients, redis_client, 2)
#                             for id, name in computed_records['device_owners'].items():
#                                 socketio.emit(
#                                     'update_patient_data',
#                                     {
#                                         'device_owner': id,
#                                         'avg_temp': computed_records['avg_temps'][id],
#                                         'graph_data': computed_records['graphs'][id],
#                                         'personal_traits': computed_records['personal_traits'][id],
#                                         'medical_history': computed_records['medical_histories'][id]
#                                     },
#                                     room=email
#                                 )
#                 else:
#                     # Start a new background thread for this doctor and patients
#                     logger.info(f"Starting new thread for {email}")
#                     patients_session[sid] = patients
#                     user_threads[email] = socketio.start_background_task(background_thread, email, patients)
#             else:
#                 logger.info("No patients selected or missing email.")
#         else:
#             logger.info("User is not authenticated. Background thread will not start yet.")

### Below is a valid option with bug
#--------------------------------------------------
# @socketio.on('get_patient_data')
# @login_required
# def handle_patients(data: dict):
#     global user_threads, stop_signals, patients_session
#     with thread_lock:
#         sid = request.sid
#         email: str = data.get('email')
#         new_patients: list = data.get('patients')

#         user_sessions[email] = sid
#         join_room(email, sid=sid)

#         if email not in stop_signals:
#             stop_signals[email] = threading.Event()
#         else:
#             stop_signals[email].clear()

#         if email and new_patients:
#             # If the thread already exists for this doctor, check if patients have changed
#             if email in user_threads:
#                 existing_patients = patients_session.get(sid, [])
#                 logger.info(f"Existing patients: {existing_patients}")
#                 logger.info(f"New patients: {new_patients}")
                
#                 # Determine which patients are new and which were removed
#                 added_patients = list(set(new_patients) - set(existing_patients))
#                 removed_patients = list(set(existing_patients) - set(new_patients))

#                 if added_patients or removed_patients:
#                     logger.info(f"Patients added: {added_patients}, Patients removed: {removed_patients}")
                    
#                     # Stop the thread if patients were removed
#                     if removed_patients:
#                         logger.info(f"Stopping thread for {email} due to removed patients")
#                         stop_signals[email].set()  # Stop the current thread
#                         del user_threads[email]     # Remove the old thread reference

#                     # Start a new thread with the updated patient list
#                     logger.info(f"Restarting thread for {email} with new patient list")
#                     patients_session[sid] = new_patients
#                     user_threads[email] = socketio.start_background_task(background_thread, email, new_patients)

#                 else:
#                     # No changes in patient list, keep the existing thread running
#                     logger.info(f"No changes in patient list for {email}. Continuing existing thread.")
#                     # Optionally, trigger an immediate update without restarting the thread
#                     with app.app_context():
#                         computed_records = compute_kpis(email, new_patients, redis_client, 2)
#                         for id, name in computed_records['device_owners'].items():
#                             socketio.emit(
#                                 'update_patient_data',
#                                 {
#                                     'device_owner': id,
#                                     'avg_temp': computed_records['avg_temps'][id],
#                                     'graph_data': computed_records['graphs'][id],
#                                     'personal_traits': computed_records['personal_traits'][id],
#                                     'medical_history': computed_records['medical_histories'][id]
#                                 },
#                                 room=email
#                             )

#             else:
#                 # No existing thread, start a new one
#                 logger.info(f"Starting new thread for {email} with patients {new_patients}")
#                 patients_session[sid] = new_patients
#                 user_threads[email] = socketio.start_background_task(background_thread, email, new_patients)

#         else:
#             logger.info("No patients selected or missing email.")

@socketio.on('get_patient_data')
@login_required
def handle_patients(data: dict):
    global user_threads, stop_signals, patients_session
    with thread_lock:
        sid = request.sid
        email: str = data.get('email')
        new_patients: list = data.get('patients')

        user_sessions[email] = sid
        # join_room(email, sid=sid)

        if email not in stop_signals:
            stop_signals[email] = threading.Event()

        if email not in patients_session: #The first time starting the app. The first time user logs.
            logger.info(f"1-Starting new thread for {email} with patients {new_patients}")
            patients_session[email] = new_patients
            user_threads[email] = socketio.start_background_task(background_thread, email)
        
        else:
            if email and new_patients:
                # If the thread already exists, update the patient list dynamically
                if email in user_threads:
                    existing_patients = patients_session.get(email, [])
                    logger.info(f"Existing patients: {existing_patients}")
                    logger.info(f"New patients: {new_patients}")

                    # Update the patient list for the existing thread
                    patients_session[email] = new_patients
                    logger.info(f"Updated patient list for {email} in the existing thread")

                    # Optionally emit a message to the client about removed patients
                    removed_patients = list(set(existing_patients) - set(new_patients))
                    if removed_patients:
                        logger.info(removed_patients)
                        socketio.emit('remove_patients', {'removed_patients': removed_patients}, room=email)
                else:
                    # If no existing thread, start a new one
                    logger.info(f"2-Starting new thread for {email} with patients {new_patients}")
                    patients_session[email] = new_patients
                    user_threads[email] = socketio.start_background_task(background_thread, email)
            else:
                logger.info("No patients selected or missing email.")

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

            if page == '/notification':
                if (email not in user_threads) or (not user_threads[email].is_alive()):
                    user_threads[email] = socketio.start_background_task(monitor_critical_condition, email)
            else:
                logger.info("Received message from invalid client. Please check the rendering page.")
        else:
            logger.info("User is not authenticated. Background thread will not start yet.")

@socketio.event
def disconnect():
    global user_threads, stop_signals
    email = request.args.get('email')
    sid = request.sid
    
    if email in user_sessions and user_sessions[email] == sid:
        leave_room(email, sid=sid)
        del user_sessions[email]

    # Check if there is a stop_signal for this email
    stop_signal = stop_signals.get(email)
    if stop_signal:
        stop_signal.set()  # Gracefully stop any background threads

    with thread_lock:
        # Safely remove user threads and stop signals
        user_threads.pop(email, None)  # Remove if exists, otherwise do nothing
        stop_signals.pop(email, None)  # Remove if exists, otherwise do nothing

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
                if (email not in user_threads) or (not user_threads[email].is_alive()):
                    user_threads[email]['monitor_patient'] = socketio.start_background_task(background_thread, email)

            elif page == '/notification':
                if (email not in user_threads) or (not user_threads[email].is_alive()):
                    user_threads[email]['critical_conditions'] = socketio.start_background_task(monitor_critical_condition, email)

@socketio.on('server_response')
def handle_connect():
    email = request.args.get('email')
    # Once connected, emit a message to the client
    # socketio.emit('server_response', {'data': 'Connected to server'}, room=str(current_user.email))
    if email:
        # Store the user's session ID mapped to their email
        user_sessions[email] = request.sid
        # Add the user to their own room (identified by their email)
        join_room(email, sid = user_sessions[email])
        # Emit a response to the client to confirm connection
        socketio.emit('server_response', {'data': 'Connected to server'}, room=email)
    else:
        logger.info('Email not found in connection request.')
    
@socketio.on("send_patient_message")
def handle_patient_message(data:dict):
    # with app.app_context():
    try:
        # print(f"Received send_patient_message event with data: {data}")
        logger.info("Received send_patient_message event with data: ", data)

        # email = data.get('email')
        # sid = request.sid
        patient_name = data.get('patient_name')
        message = data.get('message')
        device_owner = data.get('device_owner')
        flag = data.get('publish_flag')

        if not all([patient_name, message, device_owner]):
            logger.warning("Incomplete message data received.")
            socketio.emit('message_saved', {
                'status': 'error',
                'message': 'Missing required data',
                'table_name': 'patient_messages'
            })
            return
        
        # join_room(email, sid=sid)
        new_message = PatientMessage(
            patient_name=patient_name,
            device_owner=device_owner,
            message=message,
            status_flag = flag,
            timestamp=datetime.now()  # Automatically record the timestamp of when the message is received
        )
        logger.info("Adding message to the database...")
        db.session.add(new_message)
        db.session.commit()  # Write the record to the database
        logger.info(f"Message from {patient_name} (device owner: {device_owner}) saved to the database.")

        # Optionally send confirmation to the client
        socketio.emit('message_saved', {'status': 'success', 'message': 'Message saved successfully', 'patient_name': patient_name})
    except Exception as e:
        db.session.rollback()  # Rollback the transaction in case of error
        logger.error(f"Error saving message: {str(e)}", exc_info=True)
        socketio.emit('message_saved', {'status': 'error', 'message': 'Failed to save message', 'patient_name': patient_name})

