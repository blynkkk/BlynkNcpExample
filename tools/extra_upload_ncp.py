import os
import sys
import time
import requests
import fnmatch
import json
import subprocess

Import("env")

class dotdict(dict):
    __getattr__ = dict.get
    __setattr__ = dict.__setitem__
    __delattr__ = dict.__delitem__

pioenv = env["PIOENV"]

custom_ncp = dotdict({})
custom_ncp.flasher      = env.GetProjectOption("custom_ncp.flasher", "BlynkNcpFlasher, esptool")
custom_ncp.firmware     = env.GetProjectOption("custom_ncp.firmware", None)
custom_ncp.firmware_ver = env.GetProjectOption("custom_ncp.firmware_ver", "latest")
custom_ncp.upload_speed = env.GetProjectOption("custom_ncp.upload_speed", "460800")
custom_ncp.manual_reset = env.GetProjectOption("custom_ncp.manual_reset", False)
custom_ncp.erase_all    = env.GetProjectOption("custom_ncp.erase_all", True)
custom_ncp.use_stub     = env.GetProjectOption("custom_ncp.use_stub", True)
if custom_ncp.manual_reset:
    custom_ncp.before_upload = env.GetProjectOption("custom_ncp.before_upload",  "no_reset")
    custom_ncp.after_upload  = env.GetProjectOption("custom_ncp.after_upload",   "no_reset")
else:
    custom_ncp.before_upload = env.GetProjectOption("custom_ncp.before_upload",  "default_reset")
    custom_ncp.after_upload  = env.GetProjectOption("custom_ncp.after_upload",   "hard_reset")
custom_ncp.pre_upload_message = env.GetProjectOption("custom_ncp.pre_upload_message", None)
custom_ncp.post_upload_message = env.GetProjectOption("custom_ncp.post_upload_message", None)

hint_no_flasher = """
Please follow the official firmware flashing guide. This is usually provided by the module vendor.
Blynk.NCP is shipped as a combined firmware, so you only need to flash a single file (flash at address 0).

Select the firmware file, corresponding to your module type:
https://docs.blynk.io/en/getting-started/supported-boards#connectivity-modules-supported-by-blynk.ncp
"""

press_enter_msg = """

Press [Enter] when ready.
"""

def check_exec(cmd):
    if env.Execute(cmd):
        env.Exit(1)

def download_file(url, filename):
    with requests.get(url, stream=True) as r:
        r.raise_for_status()
        with open(filename, 'wb') as f:
            for chunk in r.iter_content(chunk_size=8192):
                f.write(chunk)


def get_release_info(release):
    repo = "blynkkk/BlynkNcpDriver"
    now = int(time.time())

    if release is None:
        release = "latest"

    cached_info = f".pio/BlynkNCP/.cache/{release}.json"

    try:
        with open(cached_info, "r") as f:
            data = json.load(f)

        if release == "latest" and now - data["timestamp"] > 24*60*60:
            need_get_info = True
        else:
            need_get_info = False
    except:
        need_get_info = True

    if need_get_info:
        print("Getting Blynk.NCP release info")
        if release == "latest":
            url = f"https://api.github.com/repos/{repo}/releases/latest"
        else:
            url = f"https://api.github.com/repos/{repo}/releases/tags/{release}"

        with requests.get(url) as r:
            r.raise_for_status()
            data = r.json()
            data["timestamp"] = now

        os.makedirs(".pio/BlynkNCP/.cache/", exist_ok=True)
        with open(cached_info, "w") as f:
            json.dump(data, f)

    return data

def get_download_url(filename, release_info):
    for asset in release_info["assets"]:
        asset_name = asset["name"]
        if fnmatch.fnmatch(asset_name, filename):
            return (asset_name, asset["browser_download_url"])

    tag = release_info["tag_name"]
    raise Exception(f"{filename} not found in Blynk.NCP {tag}")

def fetch_ncp(filename, release = None):
    ncp_path = f".pio/BlynkNCP/{release}/"
    ncp_full = ncp_path + filename
    if os.path.exists(ncp_full):
        return ncp_full

    try:
        release_info = get_release_info(release)
    except:
        raise Exception(f"Cannot get {release} release info")

    tag = release_info["tag_name"]
    ncp_path = f".pio/BlynkNCP/{tag}/"
    ncp_full = ncp_path + filename
    if os.path.exists(ncp_full):
        return ncp_full

    (fn, url) = get_download_url(filename, release_info)
    ncp_full = ncp_path + fn
    if not os.path.exists(ncp_full):
        print(f"Downloading {fn} ...")
        os.makedirs(ncp_path, exist_ok=True)
        download_file(url, ncp_full)
    return ncp_full

def upload_ncp(*args, **kwargs):

    flashers = custom_ncp.flasher.split(",")
    flashers = list(filter(None, flashers))     # remove empty
    flashers = list(map(str.strip, flashers))   # strip all items

    if not len(flashers):
        print(hint_no_flasher)
        sys.exit(1)

    if custom_ncp.firmware is None:
        print("custom_ncp.firmware not specified")
        sys.exit(1)

    firmware = fetch_ncp(f"BlynkNCP_{custom_ncp.firmware}", custom_ncp.firmware_ver)

    for flasher in flashers:
        if flasher == "BlynkNcpFlasher":
            # Build and upload the flasher utility
            check_exec(f"pio run -d tools/BlynkNcpFlasher -e {pioenv} --target upload")
        elif flasher == "esptool":
            time.sleep(3)
            if custom_ncp.pre_upload_message:
                input(custom_ncp.pre_upload_message + press_enter_msg)

            check_exec(' '.join(["pio", "pkg", "exec",
                "-p", "tool-esptoolpy", "--", "esptool.py",
                "" if custom_ncp.use_stub else "--no-stub",
                "--baud",   custom_ncp.upload_speed,
                "--before", custom_ncp.before_upload,
                "--after",  custom_ncp.after_upload,
                "write_flash",
                #"--flash_mode", "dio", TODO: flash_mode
                #"--flash_freq", "40m", TODO: f_flash
                "--flash_size", "detect",
                "--erase-all" if custom_ncp.erase_all else "",
                "0x0", firmware
            ]))

            if custom_ncp.post_upload_message:
                input(custom_ncp.post_upload_message + press_enter_msg)
        elif flasher == "flash_wio_terminal":
            time.sleep(3)
            if custom_ncp.pre_upload_message:
                input(custom_ncp.pre_upload_message + press_enter_msg)

            check_exec(' '.join(["python3",
                "tools/flash_wio_terminal.py",
                firmware
            ]))

            if custom_ncp.post_upload_message:
                input(custom_ncp.post_upload_message + press_enter_msg)
        else:
            raise Exception(f"Flasher {flasher} is invalid")

env.AddCustomTarget(
    name="upload_ncp",
    dependencies=None,
    actions=upload_ncp,
    title="Upload Blynk.NCP firmware"
)
