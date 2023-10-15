import sys, os, json, serial, re, requests, time, binascii, datetime
from pathlib import Path
import tkinter as tk
from tkinter import ttk, messagebox
from config import BR_KEY, BR_URL
import serial.tools.list_ports as port_list

#linux beep:
# sudo apt install beep
# sudo usermod -aG input badgereader
#linux ch340 serial:
# sudo apt autoremove brltty
# sudo usermod -aG dialout badgereader


os_linux = "linux" in sys.platform

if not os_linux:
    import winsound

# V0.1: initial version
# 0.2: for windows or linux
# 0.3: bugfix
# 0.4: fast development
# 0.5: bugfix for linux


version = "V0.5 @ MB"

class Config():
    def __init__(self):
        if os_linux:
            config_dir = Path(".")
        else:
            lap_dir = Path(os.getenv("LOCALAPPDATA"))
            config_dir = lap_dir / "rfidusb"
            if not os.path.exists(config_dir):
                os.mkdir(config_dir)
        self.config_path = config_dir / "config.json"
        if not self.config_path.exists():
            with open(self.config_path, "w") as config_file:
                config_file.write(json.dumps({"location": ""}))
        with open(self.config_path, "r") as config_file:
            self.config = json.loads(config_file.read())

    def save(self):
        with open(self.config_path, "w") as config_file:
            config_file.write(json.dumps(self.config))


class Rfid7941W():
    read_uid = bytearray(b'\xab\xba\x00\x10\x00\x10')
    resp_len = 2405

    def init(self, location, serial_port, config, gui):
        self.gui = gui
        self.location = location
        self.port = serial_port
        self.config = config
        self.ctr = 0
        self.prev_code = ""

    def kick(self):
        self.port.write(self.read_uid)
        rcv_raw = self.port.read(self.resp_len)
        if rcv_raw:
            rcv = binascii.hexlify(rcv_raw).decode("UTF-8")
            if rcv[6:8] == "81":  # valid uid received
                code = rcv[10:18]
                if code != self.prev_code or self.ctr > 5:
                    timestamp = datetime.datetime.now().isoformat().split(".")[0]
                    try:
                        ret = requests.post(f"{BR_URL}/api/registration/add", headers={'x-api-key': BR_KEY},
                                            json={"location_key": self.location, "badge_code": code, "timestamp": timestamp})
                    except Exception as e:
                        self.gui.log_add_line(f"requests.post() threw exception: {e}")
                        return
                    if ret.status_code == 200:
                        res = ret.json()
                        if res["status"]:
                            self.gui.log_add_line(f"OK, {code} at {timestamp}")
                            if os_linux:
                                os.system("beep -f 1500 -l 200")
                            else:
                                winsound.Beep(1500, 200)
                        else:
                            self.gui.log_add_line(f"FOUT, {code} at {timestamp}")
                            if os_linux:
                                os.system("beep -f 1500 -l 800")
                            else:
                                winsound.Beep(1500, 800)
                    self.ctr = 0
                self.prev_code = code
                self.ctr += 1
                time.sleep(0.1)


class BadgeServer():
    com_ports = []
    running = True
    rfid_active = False

    def __init__(self, config, gui, rfid):
        self.config = config
        self.gui = gui
        self.rfid = rfid

    def init(self):
        if os_linux:
            self.com_ports = [p.name for p in port_list.comports() if "usb" in p.name.lower()]
        else:
            self.com_ports = [p.description for p in list(port_list.comports()) if "ch340" in p.description.lower()]
        self.gui.init(self)
        while self.running:
            self.gui.kick()
            if self.rfid_active:
                self.rfid.kick()

    def start(self):
        com_port = None
        if os_linux:
            com_port = "/dev/" + self.port_name
        else:
            port_match = re.search(r"\((.*)\)", self.port_name)
            if port_match:
                com_port = port_match[1]
        if com_port:
            self.port = serial.Serial(com_port, baudrate=115200, bytesize=serial.EIGHTBITS, parity=serial.PARITY_NONE, stopbits=serial.STOPBITS_ONE, timeout=0.1)
            location = self.locations[self.location_tag]
            self.rfid.init(location, self.port, self.config, self.gui)
            self.rfid_active = True
            self.gui.log_add_line(f"OK, seriële poort {com_port} in gebruik")
            return True
        self.gui.log_add_line(f"FOUT, kan geen seriële poort gebruiken")
        return False

    def exit(self):
        self.running = False

    def get_com_ports(self):
        return self.com_ports

    def get_default_com_port(self):
        self.port_name = ""
        if self.com_ports:
            self.port_name = self.com_ports[0]
        return self.port_name

    def set_com_port(self, port):
        self.port_name = port
        return True

    def get_locations(self):
        try:
            ret = requests.get(f"{BR_URL}/api/location/get", headers={'x-api-key': BR_KEY})
            if ret.status_code == 200:
                self.locations = {tag: location for location, tag in json.loads(ret.text).items()}
                location_tags = sorted([tag for tag, _ in self.locations.items()])
                return location_tags
            return []
        except Exception as e:
            return []

    def get_default_location(self):
        if self.config.config["location"] != "":
            self.location_tag = self.config.config["location"]
        elif self.locations:
            self.location_tag = sorted([tag for tag, _ in self.locations.items()])[0]
        else:
            self.location_tag = ""
        return self.location_tag

    def set_location(self, tag):
        self.location_tag = tag
        self.config.config["location"] = tag
        self.config.save()
        return True


class GUI():
    lb_out_text = []

    def init(self, server):
        self.server = server
        self.root = tk.Tk()
        self.root.title(f"Badgereader USB, {version}")
        self.root.columnconfigure(0, weight=2)
        self.root.columnconfigure(1, weight=2)

        self.lb_out_var = tk.StringVar()
        lb_out = ttk.Label(self.root, width=50, textvariable=self.lb_out_var)
        lb_out.grid(column=0, row=3, padx=5, pady=5)

        ttk.Label(text="Seriële poort").grid(column=1, row=0, padx=5, pady=5)
        self.selected_com = tk.StringVar()
        cb_com_port = ttk.Combobox(self.root, textvariable=self.selected_com, values=server.get_com_ports(), state="readonly", width=50)
        cb_com_port.set(server.get_default_com_port())
        cb_com_port.grid(column=0, row=0, padx=5, pady=5)
        def com_port_changed(event):
            ret = server.set_com_port(cb_com_port.get())
            if not ret:
                self.log_add_line(f"Kan de poort {cb_com_port.get()} niet vinden/instellen.")
        cb_com_port.bind("<<ComboboxSelected>>", com_port_changed)

        ttk.Label(text="Locatie").grid(column=1, row=1, padx=5, pady=5)
        self.selected_location = tk.StringVar()
        cb_location = ttk.Combobox(self.root, textvariable=self.selected_location, state="readonly", width=50)
        cb_location.grid(column=0, row=1, padx=5, pady=5)
        locations = self.server.get_locations()
        if locations:
            cb_location["values"] = locations
            cb_location.set(server.get_default_location())
        else:
            self.log_add_line("Kan niet verbinden met de badgereader-server")
        def location_changed(event):
            ret = server.set_location(cb_location.get())
            if not ret:
                self.log_add_line(f"Kan de locatie {cb_location.get()} niet instellen.")
        cb_location.bind("<<ComboboxSelected>>", location_changed)

        bt_start = ttk.Button(text="Start", command=self.server.start)
        bt_start.grid(column=0, row=2, padx=5, pady=5)

        self.root.protocol("WM_DELETE_WINDOW", server.exit)

    def log_add_line(self, line):
        self.lb_out_text.append(line)
        self.lb_out_text = self.lb_out_text[-30:]
        text = "\n".join(self.lb_out_text)
        self.lb_out_var.set(text)

    def kick(self):
        self.root.update_idletasks()
        self.root.update()


def main():
    config = Config()
    gui = GUI()
    rfid = Rfid7941W()
    server = BadgeServer(config, gui, rfid)
    server.init()

if __name__ == '__main__':
    main()