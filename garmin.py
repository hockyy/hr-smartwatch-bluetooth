import asyncio
import threading
import queue
import tkinter as tk
from tkinter import ttk, messagebox
from bleak import BleakClient, BleakScanner
import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
import json
import time
from dataclasses import dataclass
from typing import Optional

# UUID for the Heart Rate Measurement characteristic
HR_MEASUREMENT_UUID = "00002a37-0000-1000-8000-00805f9b34fb"
HR_SERVICE_UUID = "0000180d-0000-1000-8000-00805f9b34fb"

# Global variables
gui_queue = queue.Queue()
selected_device = None

@dataclass
class HeartRateData:
    heart_rate: int
    timestamp: float
    device_name: str
    device_address: str
    is_connected: bool

# Global heart rate data store
current_hr_data = HeartRateData(
    heart_rate=0,
    timestamp=time.time(),
    device_name="Not Connected",
    device_address="",
    is_connected=False
)

# FastAPI app
app = FastAPI(title="Heart Rate Monitor API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve static files
app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/api/heartrate")
def get_heart_rate():
    """Get current heart rate data as JSON"""
    return {
        "heart_rate": current_hr_data.heart_rate,
        "timestamp": current_hr_data.timestamp,
        "device_name": current_hr_data.device_name,
        "device_address": current_hr_data.device_address,
        "is_connected": current_hr_data.is_connected,
        "last_update": time.time() - current_hr_data.timestamp
    }

@app.get("/api/status")
def get_status():
    """Get connection status"""
    return {
        "is_connected": current_hr_data.is_connected,
        "device_name": current_hr_data.device_name,
        "last_heartbeat": time.time() - current_hr_data.timestamp
    }

def hr_measurement_handler(sender: int, data: bytearray):
    """Notification callback for heart rate measurement."""
    global current_hr_data
    
    flag = data[0]
    if flag & 1 == 0:
        heart_rate = data[1]
    else:
        heart_rate = int.from_bytes(data[1:3], byteorder="little")
    
    # Update global data
    current_hr_data.heart_rate = heart_rate
    current_hr_data.timestamp = time.time()
    current_hr_data.is_connected = True
    
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
        "GARMIN": ["88:", "C4:", "00:", "A4:", "14:"],
        "POLAR": ["A0:", "00:", "B8:"],
        "FITBIT": ["FC:", "FB:", "2C:"],
        "SUUNTO": ["00:", "B4:"],
        "AMAZFIT": ["C8:", "A4:", "E8:"],
        "WAHOO": ["90:", "58:"],
    }
    
    for manufacturer, prefixes in mac_patterns.items():
        if any(address_upper.startswith(prefix) for prefix in prefixes):
            hints.append(f"{manufacturer}")
    
    # Check for heart rate service
    if services:
        service_uuids = [str(uuid).lower() for uuid in services]
        if HR_SERVICE_UUID.lower() in service_uuids or "180d" in service_uuids:
            hints.append("❤️ HR")
        if "180f" in service_uuids:
            hints.append("🔋 BAT")
    
    return " | ".join(hints) if hints else "Unknown"

async def scan_for_devices_fast():
    """Fast scan for available BLE devices."""
    print("Quick scanning for BLE devices...")
    # Reduced timeout for faster scanning
    devices = await BleakScanner.discover(timeout=3.0, return_adv=True)
    return devices

async def test_heart_rate_connection(device_address):
    """Test if a device supports heart rate monitoring."""
    try:
        async with BleakClient(device_address, timeout=5.0) as client:
            if client.is_connected:
                services = client.services
                for service in services:
                    if service.uuid.lower() == HR_SERVICE_UUID.lower():
                        return True, "✅ HR Service Found!"
                return False, "❌ No HR Service"
            else:
                return False, "❌ Connection Failed"
    except Exception as e:
        return False, f"❌ Error: {str(e)[:30]}..."

async def run_client(device_address, device_name):
    """Async function that connects to the device and subscribes to heart rate notifications."""
    global current_hr_data
    
    try:
        async with BleakClient(device_address, timeout=10.0) as client:
            if client.is_connected:
                print(f"Connected to {device_address}")
                current_hr_data.device_name = device_name
                current_hr_data.device_address = device_address
                current_hr_data.is_connected = True
                
                try:
                    await client.start_notify(HR_MEASUREMENT_UUID, hr_measurement_handler)
                    print("Subscribed to Heart Rate notifications...")
                    
                    while client.is_connected:
                        await asyncio.sleep(1)
                        
                except Exception as e:
                    gui_queue.put(f"Error: {str(e)}")
                    print(f"Failed to subscribe to heart rate notifications: {e}")
                    current_hr_data.is_connected = False
            else:
                print("Failed to connect.")
                gui_queue.put("Connection failed")
                current_hr_data.is_connected = False
    except Exception as e:
        print(f"An error occurred: {e}")
        gui_queue.put(f"Error: {str(e)}")
        current_hr_data.is_connected = False

def start_ble_loop(device_address, device_name):
    """Starts the asyncio loop for Bleak in a separate thread."""
    asyncio.run(run_client(device_address, device_name))

def start_fastapi_server():
    """Start FastAPI server in a separate thread."""
    def run_server():
        uvicorn.run(app, host="127.0.0.1", port=8069, log_level="info")
    
    server_thread = threading.Thread(target=run_server, daemon=True)
    server_thread.start()
    print("FastAPI server starting at http://127.0.0.1:8069")
    print("Access here: http://127.0.0.1:8069/static/obs_display.html")

class ModernDeviceSelectionWindow:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("❤️ Heart Rate Monitor - Device Selection")
        self.root.geometry("1000x700")
        self.root.configure(bg="#f0f0f0")
        
        # Modern styling
        self.style = ttk.Style()
        self.style.theme_use('clam')
        
        self.devices = []
        self.selected_device = None
        
        self.create_modern_widgets()
        self.scan_devices()
        
    def create_modern_widgets(self):
        # Main container
        main_frame = tk.Frame(self.root, bg="#2c3e50", padx=20, pady=20)
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        # Title section
        title_frame = tk.Frame(main_frame, bg="#2c3e50")
        title_frame.pack(fill=tk.X, pady=(0, 20))
        
        title_label = tk.Label(title_frame, text="🫀 Heart Rate Monitor", 
                              font=("Helvetica", 24, "bold"), 
                              bg="#2c3e50", fg="#ecf0f1")
        title_label.pack()
        
        subtitle_label = tk.Label(title_frame, text="Select your heart rate device", 
                                 font=("Helvetica", 12), 
                                 bg="#2c3e50", fg="#bdc3c7")
        subtitle_label.pack(pady=(5, 0))
        
        # Control panel
        control_frame = tk.Frame(main_frame, bg="#34495e", relief=tk.RAISED, bd=2)
        control_frame.pack(fill=tk.X, pady=(0, 20), padx=10)
        
        # Filter controls
        filter_frame = tk.Frame(control_frame, bg="#34495e")
        filter_frame.pack(pady=15, padx=20)
        
        self.show_only_hr = tk.BooleanVar()
        hr_checkbox = tk.Checkbutton(filter_frame, text="❤️ Only HR devices",
                                    variable=self.show_only_hr, 
                                    command=self.apply_filters,
                                    bg="#34495e", fg="#ecf0f1",
                                    selectcolor="#e74c3c",
                                    font=("Helvetica", 10))
        hr_checkbox.pack(side=tk.LEFT, padx=10)
        
        # Signal strength filter
        signal_frame = tk.Frame(filter_frame, bg="#34495e")
        signal_frame.pack(side=tk.LEFT, padx=20)
        
        tk.Label(signal_frame, text="Min Signal:", 
                bg="#34495e", fg="#ecf0f1", font=("Helvetica", 10)).pack(side=tk.LEFT)
        
        self.min_rssi = tk.IntVar(value=-75)
        rssi_scale = tk.Scale(signal_frame, from_=-100, to=-30, 
                             orient=tk.HORIZONTAL, variable=self.min_rssi,
                             command=lambda x: self.apply_filters(),
                             bg="#34495e", fg="#ecf0f1", 
                             highlightbackground="#34495e")
        rssi_scale.pack(side=tk.LEFT, padx=10)
        
        # Buttons
        btn_frame = tk.Frame(filter_frame, bg="#34495e")
        btn_frame.pack(side=tk.RIGHT, padx=10)
        
        refresh_btn = tk.Button(btn_frame, text="🔄 Quick Scan", 
                               command=self.scan_devices,
                               font=("Helvetica", 11, "bold"), 
                               bg="#27ae60", fg="white",
                               relief=tk.FLAT, padx=20, pady=8)
        refresh_btn.pack(side=tk.LEFT, padx=5)
        
        server_btn = tk.Button(btn_frame, text="🌐 Start Server", 
                              command=self.start_server,
                              font=("Helvetica", 11, "bold"), 
                              bg="#3498db", fg="white",
                              relief=tk.FLAT, padx=20, pady=8)
        server_btn.pack(side=tk.LEFT, padx=5)
        
        # Status
        self.status_label = tk.Label(control_frame, text="Ready to scan...", 
                                   font=("Helvetica", 11), 
                                   bg="#34495e", fg="#f39c12")
        self.status_label.pack(pady=(0, 15))
        
        # Progress bar
        self.progress = ttk.Progressbar(control_frame, mode='indeterminate')
        self.progress.pack(pady=(0, 15), padx=20, fill=tk.X)
        
        # Device list container
        list_frame = tk.Frame(main_frame, bg="#ecf0f1", relief=tk.SUNKEN, bd=2)
        list_frame.pack(fill=tk.BOTH, expand=True, padx=10)
        
        # Scrollable device list
        self.canvas = tk.Canvas(list_frame, bg="#ecf0f1")
        self.scrollbar = ttk.Scrollbar(list_frame, orient="vertical", command=self.canvas.yview)
        self.scrollable_frame = tk.Frame(self.canvas, bg="#ecf0f1")
        
        self.scrollable_frame.bind(
            "<Configure>",
            lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        )
        
        self.canvas.create_window((0, 0), window=self.scrollable_frame, anchor="nw")
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        
        self.canvas.pack(side="left", fill="both", expand=True)
        self.scrollbar.pack(side="right", fill="y")
        
    def start_server(self):
        """Start the FastAPI server."""
        start_fastapi_server()
        messagebox.showinfo("Server Started", 
                           "FastAPI server started!\n\n" +
                           "API: http://127.0.0.1:8000/api/heartrate\n" +
                           "OBS Display: http://127.0.0.1:8000/static/obs_display.html")
    
    def apply_filters(self):
        """Apply filters to the device list."""
        if hasattr(self, 'all_devices'):
            self._update_device_list(self.all_devices)
    
    def scan_devices(self):
        """Start fast device scanning."""
        self.status_label.config(text="Fast scanning (3 seconds)...")
        self.progress.start()
        
        for widget in self.scrollable_frame.winfo_children():
            widget.destroy()
            
        scan_thread = threading.Thread(target=self._scan_devices_thread, daemon=True)
        scan_thread.start()
        
    def _scan_devices_thread(self):
        """Thread function to scan for devices."""
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            devices_data = loop.run_until_complete(scan_for_devices_fast())
            
            self.root.after(0, self._update_device_list, devices_data)
        except Exception as e:
            self.root.after(0, self._scan_error, str(e))
            
    def _update_device_list(self, devices_data):
        """Update device list with modern cards."""
        self.progress.stop()
        self.all_devices = devices_data
        
        if not devices_data:
            self.status_label.config(text="No devices found. Ensure device is in pairing mode!")
            return
        
        # Clear existing widgets
        for widget in self.scrollable_frame.winfo_children():
            widget.destroy()
            
        # Process and filter devices
        filtered_devices = []
        
        for device_address, adv_data in devices_data.items():
            ble_device = adv_data[0]
            tmp_data = adv_data[1]
            device_name = tmp_data.local_name if hasattr(tmp_data, 'local_name') and tmp_data.local_name else "Unknown Device"
            rssi = tmp_data.rssi if hasattr(tmp_data, 'rssi') else -100
            services = tmp_data.service_uuids if hasattr(tmp_data, 'service_uuids') else []
            
            # Apply filters
            if rssi < self.min_rssi.get():
                continue
                
            has_hr_service = any(str(uuid).lower() == HR_SERVICE_UUID.lower() or "180d" in str(uuid).lower() 
                               for uuid in services)
            
            if self.show_only_hr.get() and not has_hr_service:
                continue
                
            filtered_devices.append((device_address, device_name, rssi, services, adv_data))
        
        # Sort by signal strength
        filtered_devices.sort(key=lambda x: x[2], reverse=True)
        self.status_label.config(text=f"Found {len(filtered_devices)} devices")
        
        # Create modern device cards
        for i, (device_address, device_name, rssi, services, adv_data) in enumerate(filtered_devices):
            self._create_device_card(device_address, device_name, rssi, services, i)
    
    def _create_device_card(self, device_address, device_name, rssi, services, index):
        """Create a modern device card."""
        # Card frame with rounded appearance
        card_frame = tk.Frame(self.scrollable_frame, bg="white", relief=tk.RAISED, bd=1)
        card_frame.pack(fill=tk.X, padx=15, pady=8)
        
        # Header with device name and signal
        header_frame = tk.Frame(card_frame, bg="white")
        header_frame.pack(fill=tk.X, padx=15, pady=(15, 5))
        
        # Device name
        name_label = tk.Label(header_frame, text=f"📱 {device_name}", 
                             font=("Helvetica", 14, "bold"), 
                             bg="white", fg="#2c3e50")
        name_label.pack(side=tk.LEFT, anchor="w")
        
        # Signal strength badge
        if rssi > -50:
            signal_color = "#27ae60"
            signal_text = "🟢 Strong"
        elif rssi > -70:
            signal_color = "#f39c12"
            signal_text = "🟡 Good"
        else:
            signal_color = "#e74c3c"
            signal_text = "🔴 Weak"
            
        signal_frame = tk.Frame(header_frame, bg=signal_color, relief=tk.RAISED, bd=1)
        signal_frame.pack(side=tk.RIGHT)
        
        signal_label = tk.Label(signal_frame, text=f"{signal_text} ({rssi})", 
                               font=("Helvetica", 9, "bold"), 
                               bg=signal_color, fg="white", padx=8, pady=2)
        signal_label.pack()
        
        # Device details
        details_frame = tk.Frame(card_frame, bg="white")
        details_frame.pack(fill=tk.X, padx=15, pady=5)
        
        address_label = tk.Label(details_frame, text=f"🏷️ {device_address}", 
                               font=("Helvetica", 9), 
                               bg="white", fg="#7f8c8d")
        address_label.pack(anchor="w")
        
        # Device type hints
        device_hint = get_device_type_hint(device_address, device_name, services)
        if device_hint != "Unknown":
            hint_label = tk.Label(details_frame, text=f"🔗 {device_hint}", 
                                 font=("Helvetica", 9), 
                                 bg="white", fg="#3498db")
            hint_label.pack(anchor="w")
        
        # Action buttons
        button_frame = tk.Frame(card_frame, bg="white")
        button_frame.pack(fill=tk.X, padx=15, pady=(5, 15))
        
        # Connect button (prominent)
        connect_btn = tk.Button(button_frame, text="🚀 Connect", 
                              command=lambda: self.select_device(device_address, device_name),
                              font=("Helvetica", 11, "bold"), 
                              bg="#e74c3c", fg="white",
                              relief=tk.FLAT, padx=25, pady=8)
        connect_btn.pack(side=tk.RIGHT, padx=5)
        
        # Test button
        test_btn = tk.Button(button_frame, text="🧪 Test", 
                           command=lambda: self.test_device(device_address),
                           font=("Helvetica", 10), 
                           bg="#95a5a6", fg="white",
                           relief=tk.FLAT, padx=15, pady=6)
        test_btn.pack(side=tk.RIGHT, padx=5)
    
    def test_device(self, device_address):
        """Test device with modern feedback."""
        self.status_label.config(text=f"Testing {device_address[:8]}...")
        
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
        """Show modern test results."""
        self.status_label.config(text="Test complete")
        title = "✅ Heart Rate Service Found!" if success else "❌ Test Failed"
        messagebox.showinfo(title, f"Device: {device_address}\n\n{message}")
        
    def _scan_error(self, error_msg):
        """Handle scanning errors."""
        self.progress.stop()
        self.status_label.config(text=f"Scan error: {error_msg}")
        
    def select_device(self, device_address, device_name):
        """Handle device selection with confirmation."""
        result = messagebox.askyesno("Connect Device", 
                                   f"Connect to:\n\n{device_name}\n{device_address}\n\nThis will start heart rate monitoring.")
        if result:
            print(f"Selected device: {device_name} ({device_address})")
            self.root.destroy()
            self.start_heart_rate_monitor(device_address, device_name)
            
    def start_heart_rate_monitor(self, device_address, device_name):
        """Start the modern heart rate monitoring window."""
        hr_window = ModernHeartRateMonitorWindow(device_address, device_name)
        hr_window.run()
        
    def run(self):
        self.root.mainloop()

class ModernHeartRateMonitorWindow:
    def __init__(self, device_address, device_name):
        self.device_address = device_address
        self.device_name = device_name
        self.root = tk.Tk()
        self.root.title(f"❤️ Heart Rate Monitor - {device_name}")
        self.root.geometry("600x500")
        self.root.configure(bg="#2c3e50")
        
        self.create_modern_widgets()
        self.start_connection()
        
    def create_modern_widgets(self):
        # Main container
        main_frame = tk.Frame(self.root, bg="#2c3e50", padx=30, pady=30)
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        # Header
        header_frame = tk.Frame(main_frame, bg="#34495e", relief=tk.RAISED, bd=2)
        header_frame.pack(fill=tk.X, pady=(0, 30))
        
        device_label = tk.Label(header_frame, text=f"📱 {self.device_name}", 
                               font=("Helvetica", 16, "bold"), 
                               bg="#34495e", fg="#ecf0f1", pady=15)
        device_label.pack()
        
        address_label = tk.Label(header_frame, text=self.device_address, 
                                font=("Helvetica", 10), 
                                bg="#34495e", fg="#bdc3c7", pady=15)
        address_label.pack()
        
        # Status indicator
        self.status_var = tk.StringVar(value="🔄 Connecting...")
        status_label = tk.Label(main_frame, textvariable=self.status_var, 
                               font=("Helvetica", 12), 
                               bg="#2c3e50", fg="#f39c12")
        status_label.pack(pady=10)
        
        # Heart rate display (main feature)
        hr_frame = tk.Frame(main_frame, bg="#e74c3c", relief=tk.RAISED, bd=3)
        hr_frame.pack(pady=30, padx=20, fill=tk.X)
        
        hr_title = tk.Label(hr_frame, text="❤️ HEART RATE", 
                           font=("Helvetica", 16, "bold"), 
                           bg="#e74c3c", fg="white", pady=10)
        hr_title.pack()
        
        self.heart_rate_var = tk.StringVar(value="-- bpm")
        heart_rate_label = tk.Label(hr_frame, textvariable=self.heart_rate_var, 
                                   font=("Helvetica", 48, "bold"), 
                                   bg="#e74c3c", fg="white", pady=20)
        heart_rate_label.pack()
        
        # Control buttons
        button_frame = tk.Frame(main_frame, bg="#2c3e50")
        button_frame.pack(pady=30)
        
        disconnect_btn = tk.Button(button_frame, text="❌ Disconnect", 
                                  command=self.disconnect,
                                  font=("Helvetica", 12, "bold"), 
                                  bg="#95a5a6", fg="white",
                                  relief=tk.FLAT, padx=30, pady=10)
        disconnect_btn.pack(side=tk.LEFT, padx=10)
        
        server_btn = tk.Button(button_frame, text="🌐 View API", 
                              command=self.open_api,
                              font=("Helvetica", 12, "bold"), 
                              bg="#3498db", fg="white",
                              relief=tk.FLAT, padx=30, pady=10)
        server_btn.pack(side=tk.LEFT, padx=10)
        
        # Instructions
        instructions = tk.Label(main_frame, 
                               text="💡 Heart rate data is available at:\nhttp://127.0.0.1:8000/api/heartrate",
                               font=("Helvetica", 10), 
                               bg="#2c3e50", fg="#bdc3c7", 
                               justify=tk.CENTER)
        instructions.pack(pady=20)
        
    def start_connection(self):
        """Start the BLE connection."""
        self.ble_thread = threading.Thread(target=start_ble_loop, 
                                          args=(self.device_address, self.device_name), 
                                          daemon=True)
        self.ble_thread.start()
        self.status_var.set("✅ Connected - Waiting for data...")
        
    def update_gui(self):
        """Update GUI with heart rate data."""
        while not gui_queue.empty():
            data = gui_queue.get_nowait()
            if isinstance(data, int):
                self.heart_rate_var.set(f"{data}")
                self.status_var.set("🟢 Receiving data...")
            else:
                self.status_var.set(f"⚠️ {str(data)}")
                
        self.root.after(100, self.update_gui)
        
    def disconnect(self):
        """Disconnect and return to device selection."""
        global current_hr_data
        current_hr_data.is_connected = False
        self.root.destroy()
        device_window = ModernDeviceSelectionWindow()
        device_window.run()
        
    def open_api(self):
        """Open API documentation."""
        import webbrowser
        webbrowser.open("http://127.0.0.1:8000/docs")
        
    def run(self):
        self.update_gui()
        self.root.mainloop()

def main():
    """Main function with FastAPI integration."""
    print("🫀 Starting Modern Heart Rate Monitor with API...")
    
    # Start FastAPI server
    start_fastapi_server()
    
    # Start GUI
    device_window = ModernDeviceSelectionWindow()
    device_window.run()

if __name__ == "__main__":
    main()
