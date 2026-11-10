CRICVALUE UI UPGRADE

This package upgrades the shared visual layer for the supplied Django templates.
- Reworked header, brand treatment, navigation and footer.
- Added a premium responsive matchday-intelligence theme.
- Improved cards, KPI strips, tables, chips, player panels, trade calculator and mobile layouts.
- Kept existing Django template logic, URL names, data bindings and trade-calculator JavaScript intact.
- Supports dark and light system appearance.

Replace the matching files in your Django project:
  templates/players/base.html
  static/players/site.css

Then hard-refresh the browser (Ctrl+F5). If static files are collected in production, run:
  python manage.py collectstatic
