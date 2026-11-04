#!/bin/sh
# Linux server: loads the site's environment, then runs the daily job.
set -a; . /etc/cricvalue.env; set +a
cd /srv/cricvalue || exit 1
./venv/bin/python manage.py daily_update >> /var/log/cricvalue/daily_update.log 2>&1
