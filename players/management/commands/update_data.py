import io, time, urllib.request, zipfile
from pathlib import Path
from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError

class Command(BaseCommand):
    help = ("Import Cricsheet JSON and refresh values.\n"
            "  update_data --source ipl_json        (download)\n"
            "  update_data --file C:\\path\\ipl_json.zip   (zip you downloaded yourself)\n"
            "  update_data                          (daily: last 7 days)")
    def add_arguments(self, parser):
        parser.add_argument("--source", default="recently_added_7_json")
        parser.add_argument("--file", help="local .zip or folder of .json files")
        parser.add_argument("--women", action="store_true")

    def handle(self, *a, **o):
        if o["file"]:
            src = Path(o["file"])
            if not src.exists():
                raise CommandError(f"Not found: {src}")
            if src.is_dir():
                dest = src
            else:
                dest = settings.BASE_DIR / "data" / src.stem
                dest.mkdir(parents=True, exist_ok=True)
                zipfile.ZipFile(src).extractall(dest)
        else:
            dest = settings.BASE_DIR / "data" / o["source"]
            dest.mkdir(parents=True, exist_ok=True)
            url = f"https://cricsheet.org/downloads/{o['source']}.zip"
            raw = self.download(url)
            zipfile.ZipFile(io.BytesIO(raw)).extractall(dest)
        call_command("import_cricsheet", str(dest), *(["--women"] if o["women"] else []))
        call_command("recalc_values", "--base")

    def download(self, url):
        for attempt in range(1, 4):
            try:
                self.stdout.write(f"Downloading {url} (try {attempt}/3)")
                req = urllib.request.Request(url, headers={"User-Agent": "CricValue/0.3"})
                with urllib.request.urlopen(req, timeout=60) as r:
                    buf = io.BytesIO()
                    while True:
                        chunk = r.read(65536)
                        if not chunk:
                            return buf.getvalue()
                        buf.write(chunk)
            except Exception as e:
                self.stderr.write(f"  failed: {e}")
                time.sleep(3)
        raise CommandError("Download failed. Download the zip in your browser and use --file.")
