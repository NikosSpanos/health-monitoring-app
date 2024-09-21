#!/bin/bash

# Ensure the logs directory exists
mkdir -p /doctor-web-framework/logs

# Clear the contents of app.log if it exists
if [ -f /doctor-web-framework/logs/app.log ]; then
    > /doctor-web-framework/logs/app.log
    echo "Log file cleared."
else
    touch /doctor-web-framework/logs/app.log
    echo "Log file created."
fi

# Continue with the normal start process (e.g., starting Gunicorn or Flask)
exec "$@"