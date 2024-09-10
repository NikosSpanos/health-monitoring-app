from flask import Blueprint, render_template, redirect, url_for, flash, request, session
from flask_login import login_user, logout_user, login_required, current_user
from .dataModel import Doctor, Device, DoctorDeviceMapping, DeviceRecords, Owner, MedicalRecords, db
from . import login_manager, socketio, thread_lock, thread, redis_client, app
from flask_caching import Cache
from typing import List
from datetime import datetime, timedelta
from sqlalchemy import func
import pandas as pd
import plotly.graph_objs as go
import json
import plotly

main = Blueprint('main', __name__)

@login_manager.user_loader
def load_user(user_id):
    print("USER_ID", user_id)
    # return Doctor.query.filter_by(id = user_id).get(Doctor.email)
    return Doctor.query.get(int(user_id))

@main.route('/')
def index():
    if 'doctor_id' not in session:
        return redirect(url_for('main.login'))
    return redirect(url_for('main.dashboard'))

@main.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']

        user = Doctor.query.filter_by(email=email).first()
        print("USER IS:", user)
        if user and user.password_hash == password:
            login_user(user)
            return redirect(url_for('main.dashboard'))
        else:
            flash('Invalid email or password!')
    return render_template('login.html')

@main.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('main.login'))

# Function to convert string timestamp to datetime
def convert_string_to_datetime(timestamp_str:str):
    return datetime.strptime(timestamp_str, '%Y-%m-%d %H:%M:%S')

# Compute the patient's average temperature based on a time interval
def get_avg_temperature(device_id):
    two_hours_ago = datetime.now() - timedelta(hours=2) #aggregate results for the last 2 hours.
    device_data:List[DeviceRecords] = DeviceRecords.query.filter(
        DeviceRecords.device_id == device_id
    ).all()
    
    temperatures = [record.temperature for record in device_data if convert_string_to_datetime(record.timestamp) >= two_hours_ago]
    if temperatures:
        return round(sum(temperatures) / len(temperatures), 2)
    return None

# Master function to compute the relevant KPIs for each patient
def compute_kpis(doctor_email:str, redis_conn:Cache, kpi_freshness:int, compute_type:str) -> dict:
    
    device_owners:dict = {}
    graphs:dict ={}
    personal_traits:dict ={}
    medical_histories:dict ={}
    avg_temps:dict ={}
    json_blob:dict = {}

    print("Compute type is: ", compute_type)

    # Set KPI freshness
    freshness = datetime.now() - timedelta(hours=kpi_freshness)
    
    # Retrieve the devices associated to a doctor
    devices:List[Device] = db.session.query(Device).join(DoctorDeviceMapping).filter(DoctorDeviceMapping.doctor_id == doctor_email).all()
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
            'SpO2': [record.spo2 for record in device_data]
        }
        df = pd.DataFrame(data)
        df['Timestamp'] = pd.to_datetime(df['Timestamp'])
        df.set_index('Timestamp', inplace=True)
        df_resampled = df.resample('2min').mean()

        if compute_type == "refresh":
            graph_data = {
                'x': df_resampled.index.strftime('%Y-%m-%dT%H:%M:%S').tolist(),  # Convert timestamps to string
                'y_heart_rate': df_resampled['Heart Rate'].tolist(),
                'y_spo2': df_resampled['SpO2'].tolist(),
                'device_owner': device.device_owner  # Send the device owner for identification
            }
            graphs[device.device_owner] = json.dumps(graph_data, cls=plotly.utils.PlotlyJSONEncoder)
        else:
            # JSON blob object of the Figure data
            fig = go.Figure()
            fig.add_trace(go.Scatter(x=df_resampled.index, y=df_resampled['Heart Rate'], mode='lines+markers', name='Heart Rate'))
            fig.add_trace(go.Scatter(x=df_resampled.index, y=df_resampled['SpO2'], mode='lines+markers', name='SpO2'))
            fig.update_layout(
                title=f"Device: {device.device_owner} ({device.device_id}) - Average Heart Rate and SpO2 per 5-Minute Interval",
                xaxis_title="Timestamp",
                yaxis_title="Average Value",
                xaxis=dict(tickformat="%H:%M"),
                autosize=False,
                width=900,
                height=600
            )
            graphs[device.device_owner] = json.dumps(fig, cls=plotly.utils.PlotlyJSONEncoder)
        # Body temperature KPI
        # =====================
        avg_temp = get_avg_temperature(device.device_id)
        avg_temps[device.device_owner] = avg_temp # Log Patient's body temperature to JSON Blob object

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
        medical_history = MedicalRecords.query.filter_by(medical_history_record_id=owner.medical_history_record_id).first()
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

    json_blob:dict = {
        'device_owners': device_owners,
        'graphs': graphs,
        'personal_traits': personal_traits,
        'medical_histories': medical_histories,
        'avg_temps': avg_temps
    }
    return json_blob

def background_thread(doctor_email):
    with app.app_context():
        while True:
            computed_records = compute_kpis(doctor_email, redis_client, 2, "refresh")

            for id, name in computed_records['device_owners'].items():
                # Emit data using socket.io
                socketio.emit(
                    'update_patient_data',
                    {
                        'device_owner': id,
                        'avg_temp': computed_records['avg_temps'][id],
                        'graph_data': computed_records['graphs'][id],
                        'personal_traits': computed_records['personal_traits'][id],
                        'medical_history': computed_records['medical_histories'][id]
                    },
                    namespace='/dashboard'
                )
            socketio.sleep(10)

@main.route('/dashboard')
@login_required
def dashboard():
    computed_records = {}
    # global thread
    # if 'thread' not in globals():
    #     thread = Thread(target=background_thread, args=current_user.email)
    #     thread.daemon = True
    #     thread.start()

    computed_records = compute_kpis(current_user.email, redis_client, 2, "initalize_dashboard")
    return render_template(
        'dashboard.html',
        graphs=computed_records['graphs'],
        personal_traits=computed_records['personal_traits'],
        medical_histories=computed_records['medical_histories'],
        avg_temps=computed_records['avg_temps']
    )

@socketio.on('connect')
def connect():
    global thread
    print('Client Connected')
    global thread
    with thread_lock:
        if thread is None:
            if current_user.is_authenticated:
                thread = socketio.start_background_task(background_thread, current_user.email)
            else:
                print("User is not authenticated. Background thread will not start yet.")