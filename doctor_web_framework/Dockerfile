# Use an official Python runtime as a parent image
FROM python:3.8-slim

RUN echo "BUILDING IMAGE FOR DOCTOR WEB FRAMEWORK"

# Create a non-root user
RUN useradd -ms /bin/bash celeryuser

# Set the working directory in the container
WORKDIR /doctor-web-framework

# Copy the current directory contents into the container at /app
COPY . /doctor-web-framework

# Install any needed packages specified in requirements.txt
RUN pip install --no-cache-dir -r ./requirements.txt

# Set the user to non-root
USER celeryuser

# Make port 5000 available to the world outside this container
EXPOSE 5000

# Define environment variable
# ENV FLASK_APP=run.py
# ENV FLASK_RUN_HOST=0.0.0.0
# ENV FLASK_RUN_HOST=flask-app

# Run app.py when the container launches
# CMD ["flask", "run"]
# CMD ["python", "run.py"]
# ENTRYPOINT ["gunicorn -k geventwebsocket.gunicorn.workers.GeventWebSocketWorker -w 1 -b 0.0.0.0:5000 ./app:app"]
CMD ["gunicorn", "-k", "gevent", "-w", "1", "-b", "0.0.0.0:5000", "--log-level", "debug", "app:app"]