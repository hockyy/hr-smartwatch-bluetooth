import asyncio
import threading
import queue
import tkinter as tk
from tkinter import ttk, messagebox
from bleak import BleakClient, BleakScanner

# UUID for the Heart Rate Measurement characteristic
HR_MEASUREMENT_UUID = "00002a37-0000-1000-8000-00805f9b34fb"
HR_SERVICE_UUID = "0000180d-0000-1000-8000-00805f9b34fb"

# A queue to send heart rate data from the async callback to the GUI
gui_queue = queue.Queue()

# Global variable to store selected device
selected_device = None

def hr_measurement_handler(sender: int, data: bytearray):
    """
    Notification callback for heart rate measurement.
    """
    flag = data[0]
    if flag & 1 == 0:
        heart_rate = data[1]
    else:
        heart_rate = int.from_bytes(data[1:3], byteorder="little")
    
    gui_queue.put(heart_rate)
    print(f"Heart Rate: {heart_rate} bpm")

def get_device_type_hint(address, name, services):
    """Try to guess device type based on MAC address patterns and services."""
    address_upper = address.upper()
    hints = []
    
    # Common manufacturer MAC patterns
    mac_patterns = {
        "APPLE": ["4C:", "8C:", "F0:", "3C:", "A4:", "BC:"],
        "SAMSUNG": ["C8:", "E8:", "CC:", "78:", "EC:"],
        "GARMIN": ["88:", "C4:", "00:", "A4:"],
        "POLAR": ["A0:", "00:", "B8:"],
        "FITBIT": ["FC:", "FB:", "2C:"],
        "SUUNTO": ["00:", "B4:"],
        "AMAZFIT": ["C8:", "A4:", "E8:"],
        "WAHOO": ["90:", "58:"],
    }
    
    for manufacturer, prefixes in mac_patterns.items():
        if any(address_upper.startswith(prefix) for prefix in prefixes):
            hints.append(f"Likely {manufacturer}")
    
    # Check for heart rate service
    if services:
        service_uuids = [str(uuid).lower() for uuid in services]
        if HR_SERVICE_UUID.lower() in service_uuids or "180d" in service_uuids:
            hints.append("❤️ HAS HEART RATE SERVICE")
        if "180f" in service_uuids:
            hints.append("🔋 Has Battery Service")
        if "1800" in service_uuids:
            hints.append("📱 Generic Access")
        if "1801" in service_uuids:
            hints.append("🔧 Generic Attribute")
    
    return " | ".join(hints) if hints else "Unknown type"

async def scan_for_devices_detailed():
    """Scan for available BLE devices with detailed information."""
    print("Scanning for BLE devices with detailed info...")
    devices = await BleakScanner.discover(timeout=15.0, return_adv=True)
    return devices

async def test_heart_rate_connection(device_address):
    """Test if a device supports heart rate monitoring."""
    try:
        async with BleakClient(device_address, timeout=10.0) as client:
            if client.is_connected:
                services = client.services
                # Check if heart rate service exists
                for service in services:
                    if service.uuid.lower() == HR_SERVICE_UUID.lower():
                        return True, "✅ Heart Rate Service Found!"
                return False, "❌ No Heart Rate Service"
            else:
                return False, "❌ Connection Failed"
    except Exception as e:
        return False, f"❌ Error: {str(e)[:50]}..."

async def run_client(device_address):
    """Async function that connects to the device and subscribes to heart rate notifications indefinitely."""
    try:
        async with BleakClient(device_address) as client:
            if client.is_connected:
                print(f"Connected to {device_address}")
                
                try:
                    await client.start_notify(HR_MEASUREMENT_UUID, hr_measurement_handler)
                    print("Subscribed to Heart Rate notifications...")
                    
                    while True:
                        await asyncio.sleep(1)
                except Exception as e:
                    gui_queue.put(f"Error: {str(e)}")
                    print(f"Failed to subscribe to heart rate notifications: {e}")
            else:
                print("Failed to connect.")
                gui_queue.put("Connection failed")
    except Exception as e:
        print(f"An error occurred: {e}")
        gui_queue.put(f"Error: {str(e)}")

def start_ble_loop(device_address):
    """Starts the asyncio loop for Bleak in a separate thread."""
    asyncio.run(run_client(device_address))

class DeviceSelectionWindow:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Select BLE Heart Rate Device")
        self.root.geometry("900x600")
        
        self.devices = []
        self.selected_device = None
        
        # Create GUI elements
        self.create_widgets()
        
        # Start scanning
        self.scan_devices()
        
    def create_widgets(self):
        # Title
        title_label = tk.Label(self.root, text="🫀 Heart Rate Monitor - Device Selection", 
                              font=("Helvetica", 16, "bold"))
        title_label.pack(pady=10)
        
        # Instructions
        instructions = tk.Label(self.root, 
                               text="Look for devices with '❤️ HAS HEART RATE SERVICE' or strong signal near you",
                               font=("Helvetica", 10), fg="blue")
        instructions.pack(pady=5)
        
        # Filter options
        filter_frame = tk.Frame(self.root)
        filter_frame.pack(pady=10)
        
        self.show_only_hr = tk.BooleanVar()
        hr_checkbox = tk.Checkbutton(filter_frame, text="Show only devices with Heart Rate service",
                                    variable=self.show_only_hr, command=self.apply_filters)
        hr_checkbox.pack(side=tk.LEFT, padx=10)
        
        self.min_rssi = tk.IntVar(value=-80)
        rssi_label = tk.Label(filter_frame, text="Min Signal Strength:")
        rssi_label.pack(side=tk.LEFT, padx=10)
        rssi_scale = tk.Scale(filter_frame, from_=-100, to=-30, orient=tk.HORIZONTAL,
                             variable=self.min_rssi, command=lambda x: self.apply_filters())
        rssi_scale.pack(side=tk.LEFT, padx=10)
        
        # Scanning status
        self.status_label = tk.Label(self.root, text="Scanning for devices...", font=("Helvetica", 12))
        self.status_label.pack(pady=5)
        
        # Progress bar
        self.progress = ttk.Progressbar(self.root, mode='indeterminate')
        self.progress.pack(pady=10, padx=20, fill=tk.X)
        self.progress.start()
        
        # Frame for device list
        self.devices_frame = tk.Frame(self.root)
        self.devices_frame.pack(pady=20, padx=20, fill=tk.BOTH, expand=True)
        
        # Scrollable frame for devices
        self.canvas = tk.Canvas(self.devices_frame)
        self.scrollbar = ttk.Scrollbar(self.devices_frame, orient="vertical", command=self.canvas.yview)
        self.scrollable_frame = tk.Frame(self.canvas)
        
        self.scrollable_frame.bind(
            "<Configure>",
            lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        )
        
        self.canvas.create_window((0, 0), window=self.scrollable_frame, anchor="nw")
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        
        # Buttons frame
        buttons_frame = tk.Frame(self.root)
        buttons_frame.pack(pady=10)
        
        refresh_btn = tk.Button(buttons_frame, text="🔄 Refresh Scan", command=self.scan_devices, 
                               font=("Helvetica", 12), bg="#4CAF50", fg="white")
        refresh_btn.pack(side=tk.LEFT, padx=10)
        
        help_btn = tk.Button(buttons_frame, text="❓ Help", command=self.show_help, 
                            font=("Helvetica", 12), bg="#2196F3", fg="white")
        help_btn.pack(side=tk.LEFT, padx=10)
        
    def show_help(self):
        help_text = """🔍 How to identify your heart rate monitor:

1. 💪 Make sure your device is in pairing/discoverable mode
2. 📍 Look for devices with strong signal (high RSSI, closer to 0)
3. ❤️ Devices with 'HAS HEART RATE SERVICE' are likely heart rate monitors
4. 🏷️ Check manufacturer hints (Garmin, Polar, Fitbit, etc.)
5. 🧪 Use 'Test HR' button to verify the device supports heart rate
6. 📱 Your device might show as 'Unknown Device' but still work

Common Heart Rate Monitor Brands:
• Garmin, Polar, Fitbit, Apple Watch, Samsung, Amazfit, Suunto, Wahoo

Tip: Put your heart rate monitor very close to your computer when scanning!"""
        
        messagebox.showinfo("Help - Identifying Your Device", help_text)
        
    def apply_filters(self):
        """Apply filters to the device list."""
        if hasattr(self, 'all_devices'):
            self._update_device_list(self.all_devices)
        
    def scan_devices(self):
        """Start device scanning in a separate thread."""
        self.status_label.config(text="Scanning for devices (15 seconds)...")
        self.progress.start()
        
        # Clear existing devices
        for widget in self.scrollable_frame.winfo_children():
            widget.destroy()
            
        scan_thread = threading.Thread(target=self._scan_devices_thread, daemon=True)
        scan_thread.start()
        
    def _scan_devices_thread(self):
        """Thread function to scan for devices."""
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            devices_data = loop.run_until_complete(scan_for_devices_detailed())
            
            self.root.after(0, self._update_device_list, devices_data)
        except Exception as e:
            self.root.after(0, self._scan_error, str(e))
            
    def _update_device_list(self, devices_data):
        """Update the device list in the GUI."""
        self.progress.stop()
        self.all_devices = devices_data
        
        if not devices_data:
            self.status_label.config(text="No devices found. Make sure your device is in pairing mode!")
            return
        
        # Clear existing widgets
        for widget in self.scrollable_frame.winfo_children():
            widget.destroy()
            
        # Process the devices_data dictionary
        # devices_data is a dict: {address: advertisement_data, ...}
        filtered_devices = []
        
        for device_address, adv_data in devices_data.items():
            # Get device info from advertisement data
            print(device_address)
            ble_device = adv_data[0]
            tmp_data = adv_data[1]
            device_name = tmp_data.local_name if hasattr(tmp_data, 'local_name') and tmp_data.local_name else "Unknown Device"
            rssi = tmp_data.rssi if hasattr(tmp_data, 'rssi') else -100
            services = tmp_data.service_uuids if hasattr(tmp_data, 'service_uuids') else []
            
            # RSSI filter
            if rssi < self.min_rssi.get():
                continue
                
            # Heart rate service filter
            has_hr_service = any(str(uuid).lower() == HR_SERVICE_UUID.lower() or "180d" in str(uuid).lower() 
                               for uuid in services)
            
            if self.show_only_hr.get() and not has_hr_service:
                continue
                
            filtered_devices.append((device_address, device_name, rssi, services, adv_data))
        
        # Sort by RSSI (signal strength)
        filtered_devices.sort(key=lambda x: x[2], reverse=True)
        
        self.status_label.config(text=f"Found {len(filtered_devices)} devices (filtered from {len(devices_data)})")
        
        # Display devices
        for i, (device_address, device_name, rssi, services, adv_data) in enumerate(filtered_devices):
            # Get device type hint
            device_hint = get_device_type_hint(device_address, device_name, services)
            
            # Create a frame for each device
            device_frame = tk.Frame(self.scrollable_frame, relief=tk.RAISED, borderwidth=2, bg="white")
            device_frame.pack(fill=tk.X, padx=5, pady=3)
            
            # Signal strength color coding
            if rssi > -50:
                rssi_color = "green"
            elif rssi > -70:
                rssi_color = "orange"
            else:
                rssi_color = "red"
            
            # Device info - Left side
            info_frame = tk.Frame(device_frame, bg="white")
            info_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=10, pady=5)
            
            name_label = tk.Label(info_frame, text=f"📱 {device_name}", 
                                 font=("Helvetica", 12, "bold"), bg="white", anchor="w")
            name_label.pack(anchor="w")
            
            address_label = tk.Label(info_frame, text=f"🏷️ {device_address}", 
                                   font=("Helvetica", 10), bg="white", fg="gray", anchor="w")
            address_label.pack(anchor="w")
            
            hint_label = tk.Label(info_frame, text=f"🔗 {device_hint}", 
                                 font=("Helvetica", 10), bg="white", fg="blue", anchor="w")
            hint_label.pack(anchor="w")
            
            # Buttons - Right side
            button_frame = tk.Frame(device_frame, bg="white")
            button_frame.pack(side=tk.RIGHT, padx=10, pady=5)
            
            # RSSI display
            rssi_label = tk.Label(button_frame, text=f"📶 {rssi} dBm", 
                                 font=("Helvetica", 10, "bold"), fg=rssi_color, bg="white")
            rssi_label.pack(anchor="e", pady=2)
            
            # Button row
            btn_frame = tk.Frame(button_frame, bg="white")
            btn_frame.pack(anchor="e")
            
            # Test HR button
            test_btn = tk.Button(btn_frame, text="🧪 Test HR", 
                               command=lambda addr=device_address: self.test_device(addr),
                               font=("Helvetica", 9), bg="#FF9800", fg="white", width=10)
            test_btn.pack(side=tk.LEFT, padx=2)
            
            # Connect button
            connect_btn = tk.Button(btn_frame, text="🔗 Connect", 
                                  command=lambda addr=device_address, name=device_name: self.select_device(addr, name),
                                  font=("Helvetica", 10), bg="#4CAF50", fg="white", width=10)
            connect_btn.pack(side=tk.LEFT, padx=2)
        
        # Pack scrollbar and canvas
        self.canvas.pack(side="left", fill="both", expand=True)
        self.scrollbar.pack(side="right", fill="y")
        
    def test_device(self, device_address):
        """Test if device supports heart rate monitoring."""
        self.status_label.config(text=f"Testing {device_address}...")
        
        def test_thread():
            try:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                success, message = loop.run_until_complete(test_heart_rate_connection(device_address))
                self.root.after(0, lambda: self._show_test_result(device_address, success, message))
            except Exception as e:
                self.root.after(0, lambda: self._show_test_result(device_address, False, f"Error: {str(e)}"))
        
        threading.Thread(target=test_thread, daemon=True).start()
        
    def _show_test_result(self, device_address, success, message):
        """Show test results."""
        self.status_label.config(text="Scan complete")
        title = "✅ Test Successful!" if success else "❌ Test Failed"
        messagebox.showinfo(title, f"Device: {device_address}\n\n{message}")
        
    def _scan_error(self, error_msg):
        """Handle scanning errors."""
        self.progress.stop()
        self.status_label.config(text=f"Scan error: {error_msg}")
        
    def select_device(self, device_address, device_name):
        """Handle device selection."""
        global selected_device
        selected_device = device_address
        
        result = messagebox.askyesno("Confirm Selection", 
                                   f"Connect to device:\n{device_name}\n{device_address}?")
        if result:
            print(f"Selected device: {device_name} ({device_address})")
            self.root.destroy()
            self.start_heart_rate_monitor(device_address, device_name)
            
    def start_heart_rate_monitor(self, device_address, device_name):
        """Start the heart rate monitoring window."""
        hr_window = HeartRateMonitorWindow(device_address, device_name)
        hr_window.run()
        
    def run(self):
        self.root.mainloop()

class HeartRateMonitorWindow:
    def __init__(self, device_address, device_name):
        self.device_address = device_address
        self.device_name = device_name
        self.root = tk.Tk()
        self.root.title(f"❤️ Heart Rate Monitor - {device_name}")
        self.root.geometry("500x400")
        
        self.create_widgets()
        self.start_connection()
        
    def create_widgets(self):
        # Device info
        device_info = tk.Label(self.root, text=f"Connected to: {self.device_name}\n{self.device_address}", 
                              font=("Helvetica", 12), fg="blue")
        device_info.pack(pady=10)
        
        # Connection status
        self.status_var = tk.StringVar(value="Connecting...")
        status_label = tk.Label(self.root, textvariable=self.status_var, font=("Helvetica", 10))
        status_label.pack(pady=5)
        
        # Heart rate display
        self.heart_rate_var = tk.StringVar(value="Waiting for data...")
        heart_rate_label = tk.Label(self.root, textvariable=self.heart_rate_var, 
                                   font=("Helvetica", 32), fg="red")
        heart_rate_label.pack(padx=20, pady=30)
        
        # Instructions
        instructions = tk.Label(self.root, 
                               text="💡 Make sure your heart rate monitor is worn and active",
                               font=("Helvetica", 10), fg="gray")
        instructions.pack(pady=10)
        
        # Disconnect button
        disconnect_btn = tk.Button(self.root, text="❌ Disconnect", command=self.disconnect,
                                  font=("Helvetica", 12), bg="#f44336", fg="white")
        disconnect_btn.pack(pady=20)
        
    def start_connection(self):
        """Start the BLE connection in a separate thread."""
        self.ble_thread = threading.Thread(target=start_ble_loop, args=(self.device_address,), daemon=True)
        self.ble_thread.start()
        self.status_var.set("Connected - Waiting for heart rate data...")
        
    def update_gui(self):
        """Polls the GUI queue for new heart rate data and updates the label."""
        while not gui_queue.empty():
            data = gui_queue.get_nowait()
            if isinstance(data, int):
                self.heart_rate_var.set(f"❤️ {data} bpm")
                self.status_var.set("Receiving heart rate data...")
            else:
                self.status_var.set(str(data))
                
        self.root.after(100, self.update_gui)
        
    def disconnect(self):
        """Disconnect and return to device selection."""
        self.root.destroy()
        device_window = DeviceSelectionWindow()
        device_window.run()
        
    def run(self):
        self.update_gui()
        self.root.mainloop()

def main():
    """Main function to start the application."""
    print("🫀 Starting BLE Heart Rate Monitor...")
    device_window = DeviceSelectionWindow()
    device_window.run()

if __name__ == "__main__":
    main()
