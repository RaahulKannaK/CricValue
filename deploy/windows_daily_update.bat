@echo off
REM Edit the folder below to your project folder (the one with manage.py).
cd /d "D:\raahulkanna\New_Desktop\player_rank\cricvalue_v3"
if not exist logs mkdir logs
echo ==== %date% %time% >> logs\daily_update.log
python manage.py daily_update >> logs\daily_update.log 2>&1
