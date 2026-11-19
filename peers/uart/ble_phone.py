# The simulated phone's radio: a second endpoint on the BLE medium. It only listens; the scenario's pcap is its
# receive log, decoded by scripts/ble_phone.py.
class Peer:
    def __init__(self, ctx):
        pass

    def on_byte(self, b):
        pass
