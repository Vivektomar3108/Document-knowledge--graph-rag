#!/bin/bash



# Activate the virtual environment using pyenv
source "/home/ubuntu/borges knowledge graph/venv/bin/activate"

# Change to the specified directory
cd "/home/ubuntu/borges knowledge graph/api"
# Check for processes running on port 8006
PID=$(lsof -t -i:8004)

# If PID is not empty, there's a process on port 8006
if [[ ! -z "$PID" ]]; then
    echo "Existing FastAPI Server PID on port 8004: $PID"
    
    # Check if the process with $PID is running
    if kill -0 $PID > /dev/null 2>&1; then
        kill -9 $PID
        sleep 2
        echo "" > api.out
        echo "Restarting FastAPI Server on port 8004"
    else
        echo "Process $PID not found. Starting new FastAPI Server on port 8004."
    fi
else
    echo "No existing FastAPI Server process found on port 8004."
fi

# Start the new process
nohup uvicorn main:app --host 0.0.0.0 --port 8004 --timeout-keep-alive 6000 > api.out &

# Print the PID of the new process
echo "FastAPI Server has been restarted on port 8004. New PID is $!"