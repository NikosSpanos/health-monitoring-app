from fastapi import FastAPI, Depends, Request, Form, WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session
from fastapi.templating import Jinja2Templates
from . import models, schemas, database
from fastapi.responses import HTMLResponse
from fastapi.background import BackgroundTasks
from datetime import datetime
import asyncio

app = FastAPI()
templates = Jinja2Templates(directory="app/templates")

# Store the counter of consecutive publish_flag=1 for each user
consecutive_hits = {}

# Helper function to reset the counter
def reset_consecutive_hits(user):
    global consecutive_hits
    consecutive_hits[user] = 0

# Route for the login page
@app.get("/login", response_class=HTMLResponse)
async def login(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})

# Route for logging in and redirecting to the message log page
@app.post("/login")
async def login_post(request: Request, username: str = Form(...)):
    # In a real app, you would validate the username and password
    return templates.TemplateResponse("message_log.html", {"request": request, "username": username})

# Function to check the latest message
async def check_latest_message(username: str, db: Session):
    global consecutive_hits

    if username not in consecutive_hits:
        consecutive_hits[username] = 0

    # Fetch the latest message for the user
    latest_message = db.query(models.PatientMessage).filter_by(device_owner=username).order_by(models.PatientMessage.timestamp.desc()).first()
    
    if latest_message and latest_message.status_flag == 0:
        latest_message.status_flag = 1  # Mark it as processed (publish_flag=1)
        db.commit()
        consecutive_hits[username] = 0  # Reset counter
        return {
            "message": latest_message.message,
            "patient_name": latest_message.patient_name,
            "timestamp": latest_message.timestamp.isoformat()
        }
    else:
        consecutive_hits[username] += 1
        if consecutive_hits[username] >= 5:
            # return None  # Stop showing messages if already marked for 5 hits
            return {
                "message": "No new messages",
                "patient_name": latest_message.patient_name,
                "timestamp": datetime.now().isoformat()
             }
        return {
            "message": latest_message.message,
            "patient_name": latest_message.patient_name,
            "timestamp":  datetime.now().isoformat()
        }

@app.get("/messages/{username}", response_class=HTMLResponse)
async def messages_log(request: Request, username: str, db: Session = Depends(database.get_db)):
    result = await check_latest_message(username, db)
    if result:
        message = result["message"]
        patient_name = result["patient_name"]
        timestamp = result["timestamp"]
    return templates.TemplateResponse(
        "message_log.html",
        {
            "request": request,
            "username": username,
            "patient_name": patient_name,
            "message": message or "No new messages",
            "timestamp":  timestamp
        }
    )

@app.websocket("/ws/{username}")
async def websocket_endpoint(websocket: WebSocket, username: str, db: Session = Depends(database.get_db)):
    await websocket.accept()
    try:
        while True:
            result = await check_latest_message(username, db)
            if result:
                await websocket.send_json({
                    "message": result["message"],
                    "patient_name": result["patient_name"],
                    "timestamp": result["timestamp"]
                })
            else:
                await websocket.send_json({
                    "message": "No new messages",
                    "patient_name": result["patient_name"],
                    "timestamp": datetime.now().isoformat()
                })
            await asyncio.sleep(10)
    except WebSocketDisconnect:
        print(f"WebSocket disconnected for user: {username}")