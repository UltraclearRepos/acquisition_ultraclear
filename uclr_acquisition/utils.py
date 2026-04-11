import psutil
import ipaddress
import time
import socket
from .config import config


def get_broadcast_address():

    target_interface = "Wi-Fi"
    
    for iface, addrs in psutil.net_if_addrs().items():
        if iface != target_interface:
            continue
        for addr in addrs:
            if addr.family.name == "AF_INET" and not addr.address.startswith("127."):
                ip = int(ipaddress.IPv4Address(addr.address))
                netmask = int(ipaddress.IPv4Address(addr.netmask))
                broadcast = ip | (~netmask & 0xFFFFFFFF)
                return str(ipaddress.IPv4Address(broadcast))

def get_local_ip_address():
    rpi_host = config['connection'][0]
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.connect((rpi_host, 80))
        return s.getsockname()[0]
        
def build_filename(*args, sep="_"):
    timestamp = time.strftime('%Y-%m-%d_%H.%M.%S', time.localtime())
    parts = [str(arg) for arg in args if arg and arg != ""]
    parts.append(timestamp)
    return sep.join(parts)