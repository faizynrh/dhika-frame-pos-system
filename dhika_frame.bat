@echo off

REM Aktivasi virtual environment
call .\env\Scripts\activate

REM Menjalankan aplikasi Flask
start cmd /k python app.py

REM Membuka Google Chrome dengan URL lokal Flask
start chrome http://127.0.0.1:5000

REM Menunggu hingga cmd ditutup
pause

