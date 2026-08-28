@echo off
REM Startup script for Borges Knowledge Graph API (Windows)
REM Run from the project root directory (not from api/ subdirectory)

echo Starting Borges Knowledge Graph API...

REM Check if we're in the right directory
if not exist "api\main.py" (
    echo ERROR: Please run this script from the project root directory!
    echo Current directory: %CD%
    echo Expected: The directory containing the 'api' folder
    exit /b 1
)

REM Check if .env file exists in api/
if not exist "api\.env" (
    echo ERROR: .env file not found in api\ directory!
    echo Please create api\.env file from api\.env.example
    echo   cd api
    echo   copy .env.example .env
    echo   REM Edit .env with your credentials
    exit /b 1
)

REM Create temp upload directory if it doesn't exist
if not exist "api\temp_uploads\" mkdir api\temp_uploads

REM Check dependencies
echo Checking dependencies...
python -c "import fastapi, uvicorn, sqlalchemy, boto3" 2>nul
if errorlevel 1 (
    echo Missing dependencies. Installing...
    pip install -r api\requirements.txt
)

REM Start the API server
echo.
echo ================================================================================
echo Starting API server on http://0.0.0.0:8000
echo Swagger docs: http://localhost:8000/api/v1/docs
echo ReDoc: http://localhost:8000/api/v1/redoc
echo.
echo Press Ctrl+C to stop the server
echo ================================================================================
echo.

REM Run with Python module syntax from project root
python -m uvicorn api.main:app --reload --host 0.0.0.0 --port 8000 --log-level info
