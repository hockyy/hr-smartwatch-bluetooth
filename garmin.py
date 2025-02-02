import asyncio
import threading
import queue
import tkinter as tk
from bleak import BleakClient

# Bluetooth device address and UUID for the Heart Rate Measurement characteristic
DEVICE_ADDRESS = "14:13:0B:A1:14:C0"
HR_MEASUREMENT_UUID = "00002a37-0000-1000-8000-00805f9b34fb"

# A queue to send heart rate data from the async callback to the GUI
gui_queue = queue.Queue()

def hr_measurement_handler(sender: int, data: bytearray):
    """
    Notification callback for heart rate measurement.
    The first byte is the flag.
    If the least significant bit (bit 0) is 0, the heart rate value is in one byte,
    otherwise in two bytes.
    """
    flag = data[0]
    if flag & 1 == 0:
        # Heart Rate is in 1 byte
        heart_rate = data[1]
    else:
        # Heart Rate is in 2 bytes
        heart_rate = int.from_bytes(data[1:3], byteorder="little")
    
    # Put the heart rate into the queue for the GUI thread to update.
    gui_queue.put(heart_rate)
    # Optional: print to console for debugging
    print(f"Heart Rate: {heart_rate} bpm")

async def run_client():
    """Async function that connects to the device and subscribes to heart rate notifications indefinitely."""
    try:
        async with BleakClient(DEVICE_ADDRESS) as client:
            if client.is_connected:
                print(f"Connected to {DEVICE_ADDRESS}")
                await client.start_notify(HR_MEASUREMENT_UUID, hr_measurement_handler)
                print("Subscribed to Heart Rate notifications...")
                
                # Run indefinitely. You could also wait on an asyncio.Event() if you intend to stop in a controlled fashion.
                while True:
                    await asyncio.sleep(1)
            else:
                print("Failed to connect.")
    except Exception as e:
        print(f"An error occurred: {e}")

def start_ble_loop():
    """Starts the asyncio loop for Bleak in a separate thread."""
    asyncio.run(run_client())

def main():
    # Start the Bleak asyncio client on a daemon thread.
    ble_thread = threading.Thread(target=start_ble_loop, daemon=True)
    ble_thread.start()

    # Create a simple Tkinter GUI to stream the heart rate data.
    root = tk.Tk()
    root.title("Heart Rate Monitor")

    # Configure a label to display heart rate
    heart_rate_var = tk.StringVar(value="Waiting for data...")
    heart_rate_label = tk.Label(root, textvariable=heart_rate_var, font=("Helvetica", 24))
    heart_rate_label.pack(padx=20, pady=20)

    def update_gui():
        """Polls the GUI queue for new heart rate data and updates the label."""
        while not gui_queue.empty():
            hr = gui_queue.get_nowait()
            heart_rate_var.set(f"Heart Rate: {hr} bpm")
        # Schedule next update
        root.after(100, update_gui)

    # Start updating the GUI.
    update_gui()

    # Run the Tkinter main loop.
    root.mainloop()

if __name__ == "__main__":
    main()