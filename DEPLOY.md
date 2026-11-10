# CricValue: daily updates and going online

## 1. Automatic daily updates on your Windows PC (testing)
1. Add this line to TEMPLATES -> OPTIONS -> context_processors in cricvalue/settings.py:
       "players.context.site_status",
   (it shows "Data up to ..." in the site footer)
2. Test the job once:   python manage.py daily_update
3. Edit the folder path inside deploy\windows_daily_update.bat, then schedule it (PowerShell):
       schtasks /create /tn "CricValue Daily Update" /tr "D:\path\to\cricvalue_v3\deploy\windows_daily_update.bat" /sc daily /st 06:30 /f
   The PC must be on at that time. Check logs\daily_update.log afterwards.
   Right after a long break use:  python manage.py daily_update --days 30

## 2. Putting it online (Ubuntu server with MySQL, gunicorn and nginx)
Needs a small Linux server (VPS) and a domain name. Replace yourdomain.com everywhere.

### Server packages
    sudo apt update
    sudo apt install -y python3-venv python3-dev build-essential pkg-config libmysqlclient-dev mysql-server nginx certbot python3-certbot-nginx
    sudo adduser --system --group --home /srv/cricvalue cricvalue

### Database
    sudo mysql
    CREATE DATABASE cricvalue CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
    CREATE USER 'cricvalue'@'localhost' IDENTIFIED BY 'STRONG-PASSWORD';
    GRANT ALL PRIVILEGES ON cricvalue.* TO 'cricvalue'@'localhost';
    EXIT;

### Code
Upload your project folder (manage.py, cricvalue/, players/, deploy/) to /srv/cricvalue, then:
    sudo cp deploy/wsgi.py cricvalue/wsgi.py
    sudo cp deploy/settings_prod.py cricvalue/settings_prod.py
    sudo chown -R cricvalue:cricvalue /srv/cricvalue
    sudo -u cricvalue python3 -m venv /srv/cricvalue/venv
    sudo -u cricvalue /srv/cricvalue/venv/bin/pip install -r deploy/requirements.txt
    sudo cp deploy/cricvalue.env.example /etc/cricvalue.env      # then edit it: secret key, domain, DB password
    sudo chmod 640 /etc/cricvalue.env && sudo chgrp cricvalue /etc/cricvalue.env
    sudo mkdir -p /var/log/cricvalue && sudo chown cricvalue /var/log/cricvalue
    sudo chmod +x deploy/daily_update.sh

### First run (as the cricvalue user, with the environment loaded)
    sudo -u cricvalue bash -c 'set -a; . /etc/cricvalue.env; set +a; cd /srv/cricvalue; ./venv/bin/python manage.py migrate'
    sudo -u cricvalue bash -c 'set -a; . /etc/cricvalue.env; set +a; cd /srv/cricvalue; ./venv/bin/python manage.py collectstatic --noinput'
    sudo -u cricvalue bash -c 'set -a; . /etc/cricvalue.env; set +a; cd /srv/cricvalue; ./venv/bin/python manage.py createsuperuser'
Load the data (takes a long time; run it inside tmux or screen):
    ... manage.py update_data --source all_json
(or upload your existing data\all_json.zip and use --file)

### Web service
    sudo cp deploy/cricvalue.service /etc/systemd/system/
    sudo systemctl daemon-reload && sudo systemctl enable --now cricvalue
    sudo cp deploy/nginx_cricvalue.conf /etc/nginx/sites-available/cricvalue
    sudo ln -s /etc/nginx/sites-available/cricvalue /etc/nginx/sites-enabled/
    sudo nginx -t && sudo systemctl reload nginx
    sudo certbot --nginx -d yourdomain.com -d www.yourdomain.com
Then set DJANGO_HTTPS=1 in /etc/cricvalue.env and run: sudo systemctl restart cricvalue

### Daily update and backups
    sudo cp deploy/cricvalue.cron /etc/cron.d/cricvalue

## 3. Before you tell people about it
- Keep the Cricsheet credit and the "estimates, not official prices" notice. Do not present it as betting or fantasy advice.
- The admin (/admin/) is public: use a strong password.
- Check the daily log after the first few nights: /var/log/cricvalue/daily_update.log
<<<<<<< HEAD

## Render web service start command

Use this start command for the Django web service:

```bash
gunicorn cricvalue.wsgi:application --workers 2 --threads 2 --timeout 90 --access-logfile - --error-logfile -
```

The longer timeout is only a safety margin. Player-detail requests are optimized to avoid loading a player's full career and to avoid building whole-format discovery/similarity pools during a click.
=======
>>>>>>> 32c894519d1d3703c8124559016ca18af8eb90d6
