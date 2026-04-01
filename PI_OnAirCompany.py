"""
OnAir Company X-Plane Plugin for XPPython3
Communicates with OnAir client application via TCP
"""

import xp  # type: ignore
import socket
import struct
import os
import time
import errno

import threading
from typing import Optional, Dict, Any

# --- DEFINITIONS BASED ON DECOMPILED C# STRUCTS ---

# XPlaneFuelTankStruct: 1 float, 1 int
FUEL_TANK_FMT = "fi"

# LIVE_AIRCRAFT_FMT:
# 5i (20 bytes) -> 4x (padding to reach 24) -> d (8 bytes, starts at offset 24)
# This changes the Live struct size from 264 to 272 bytes.
LIVE_AIRCRAFT_FMT = "<5i 4x d 16f 9f 8f 8i 8i f 4i 4i 8i 2i f i 2f i"

# TYPE_AIRCRAFT_FMT:
# Initial part: 2i, 6f (32 bytes)
# FuelTanks: 9 * 8 bytes (72 bytes)
# OutPath: 512 bytes
# Current Subtotal: 616 bytes
# PADDING TO 4096: 4096 - 272 (Live) - 616 (Type) = 3208 bytes
TYPE_AIRCRAFT_FMT = f"<2i 6f {9 * 8}s 512s 3208x"


class PythonInterface:
    def __init__(self):
        self.plugin_name = "OnAir Company"
        self.plugin_sig = "onair.company"
        self.plugin_description = "OnAir Company Flight Following"
        
        # Thread lock for struct packing
        self._pack_lock = threading.Lock()
        
        # Thread lock for file operations to prevent race conditions
        self._file_lock = threading.Lock()
        
        # Network settings
        self.server_ip = "127.0.0.1"
        self.server_port = 43230
        self.socket: Optional[socket.socket] = None
        self.connected = False
        self.connection_status = "Disconnected"
        
        # Packet timing and state (similar to original plugin)
        self.send_aircraft_data = True  # Flag to alternate between packet types
        self.packet_sequence = 0
        self.last_aircraft_send = 0
        
        # Flight loop
        self.flight_loop_id = None
        self.draw_callback_id = None
        
        # Data references
        self.datarefs = {}
        self.aircraft_data = {}
        
        # Plugin directory
        self.plugin_dir = None
        
        # Status colors for display
        self.status_color = [1.0, 1.0, 1.0]  # White by default
        
        # Status message timer variables
        self.current_status_message = ""
        self.current_status_color = [1.0, 1.0, 1.0]
        self.status_message_expires = 0  # Time when status message expires
        
    def XPluginStart(self):
        """Initialize the plugin"""
        xp.log("OnAir Company Plugin: XPluginStart() called")
        
        # Find plugin directory
        self.plugin_dir = xp.getSystemPath() + "Resources/plugins/OnAir.XPlanePlugin/64/"
        xp.log(f"OnAir Company Plugin: Plugin directory set to {self.plugin_dir}")
        
        # Load settings
        self.load_settings()
        
        # Initialize datarefs
        self.init_datarefs()
        
        xp.log("OnAir Company Plugin: XPluginStart() completed successfully")
        return self.plugin_name, self.plugin_sig, self.plugin_description
    
    def XPluginEnable(self):
        """Enable the plugin"""
        xp.log("OnAir Company Plugin: XPluginEnable() called")
        
        self.load_settings()
        
        # Register flight loop callback
        xp.log("OnAir Company Plugin: Registering flight loop callback")
        self.flight_loop_id = xp.createFlightLoop(self.flight_loop_callback)
        xp.scheduleFlightLoop(self.flight_loop_id, 0.2, 1)
        
        # Register draw callback
        xp.log("OnAir Company Plugin: Registering draw callback")
        self.draw_callback_id = xp.registerDrawCallback(
            self.draw_callback,
            50,  # Phase_LastCockpit equivalent
            0,
            None
        )
        
        xp.log("OnAir Company Plugin: XPluginEnable() completed - Plugin enabled successfully")
        return 1
    
    def XPluginDisable(self):
        """Disable the plugin"""
        xp.log("OnAir Company Plugin: XPluginDisable() called")
        
        # Unregister callbacks
        if self.flight_loop_id:
            xp.log("OnAir Company Plugin: Destroying flight loop")
            xp.destroyFlightLoop(self.flight_loop_id)
            self.flight_loop_id = None
            
        if self.draw_callback_id:
            xp.log("OnAir Company Plugin: Unregistering draw callback")
            xp.unregisterDrawCallback(self.draw_callback_id, 50, 0, None)
            self.draw_callback_id = None
            
        # Close socket connection
        self.disconnect()
        
        xp.log("OnAir Company Plugin: XPluginDisable() completed - Plugin disabled")
    
    def XPluginStop(self):
        """Stop the plugin"""
        xp.log("OnAir Company Plugin: XPluginStop() called")
        self.disconnect()
        xp.log("OnAir Company Plugin: XPluginStop() completed - Plugin stopped")
    
    def XPluginReceiveMessage(self, from_id, msg, param):
        """Receive messages from X-Plane"""
        pass
    
    def load_settings(self):
        """Load settings from configuration files"""
        xp.log("OnAir Company Plugin: load_settings() called")
        
        try:
            # Load server IP
            ip_file = os.path.join(self.plugin_dir, "server_ip.txt")
            if os.path.exists(ip_file):
                with open(ip_file, 'r') as f:
                    self.server_ip = f.read().strip()
                xp.log(f"OnAir Company Plugin: Loaded server IP: {self.server_ip}")
            else:
                xp.log(f"OnAir Company Plugin: Using default server IP: {self.server_ip}")
            
            # Load server port
            port_file = os.path.join(self.plugin_dir, "server_port.txt")
            if os.path.exists(port_file):
                with open(port_file, 'r') as f:
                    self.server_port = int(f.read().strip())
                xp.log(f"OnAir Company Plugin: Loaded server port: {self.server_port}")
            else:
                xp.log(f"OnAir Company Plugin: Using default server port: {self.server_port}")
                    
        except Exception as e:
            xp.log(f"OnAir Company Plugin: Error in load_settings(): {e}")
        
        xp.log("OnAir Company Plugin: load_settings() completed")
    
    def init_datarefs(self):
        """Initialize all required datarefs"""
        xp.log("OnAir Company Plugin: init_datarefs() called")
        
        try:
            self.datarefs = {
                # Position
                'elevation': xp.findDataRef("sim/flightmodel/position/elevation"),
                'latitude': xp.findDataRef("sim/flightmodel/position/latitude"),
                'longitude': xp.findDataRef("sim/flightmodel/position/longitude"),
                'y_agl': xp.findDataRef("sim/flightmodel/position/y_agl"),
                
                # Attitude
                'phi': xp.findDataRef("sim/flightmodel/position/phi"),
                'theta': xp.findDataRef("sim/flightmodel/position/theta"),
                'psi': xp.findDataRef("sim/flightmodel/position/psi"),
                'mag_psi': xp.findDataRef("sim/flightmodel/position/mag_psi"),
                
                # Speed
                'vh_ind': xp.findDataRef("sim/flightmodel/position/vh_ind"),
                'true_airspeed': xp.findDataRef("sim/flightmodel/position/true_airspeed"),
                'airspeed_kts': xp.findDataRef("sim/cockpit2/gauges/indicators/airspeed_kts_pilot"),
                'groundspeed': xp.findDataRef("sim/flightmodel/position/groundspeed"),
                
                # Aircraft state
                'onground_any': xp.findDataRef("sim/flightmodel/failures/onground_any"),
                'has_crashed': xp.findDataRef("sim/flightmodel2/misc/has_crashed"),
                'autopilot_mode': xp.findDataRef("sim/cockpit/autopilot/autopilot_mode"),
                
                # Altitude and G-force
                'altitude_ft': xp.findDataRef("sim/cockpit2/gauges/indicators/altitude_ft_pilot"),
                'gforce_normal': xp.findDataRef("sim/flightmodel2/misc/gforce_normal"),
                
                # Fuel
                'm_fuel': xp.findDataRef("sim/flightmodel/weight/m_fuel"),
                'm_fixed': xp.findDataRef("sim/flightmodel/weight/m_fixed"),
                'fuel_flow': xp.findDataRef("sim/cockpit2/engine/indicators/fuel_flow_kg_sec"),
                'num_tanks': xp.findDataRef("sim/aircraft/overflow/acf_num_tanks"),
                
                # Engines
                'engine_burning_fuel': xp.findDataRef("sim/flightmodel2/engines/engine_is_burning_fuel"),
                'engine_running': xp.findDataRef("sim/flightmodel/engine/ENGN_running"),
                'fuel_pump_on': xp.findDataRef("sim/cockpit/engine/fuel_pump_on"),
                
                # Lights
                'beacon_lights_on': xp.findDataRef("sim/cockpit/electrical/beacon_lights_on"),
                'landing_lights_on': xp.findDataRef("sim/cockpit/electrical/landing_lights_on"),
                'nav_lights_on': xp.findDataRef("sim/cockpit/electrical/nav_lights_on"),
                'strobe_lights_on': xp.findDataRef("sim/cockpit/electrical/strobe_lights_on"),
                'taxi_light_on': xp.findDataRef("sim/cockpit/electrical/taxi_light_on"),
                
                # Controls
                'flap_handle_deploy_ratio': xp.findDataRef("sim/cockpit2/controls/flap_handle_deploy_ratio"),
                'gear_handle_down': xp.findDataRef("sim/cockpit2/controls/gear_handle_down"),
                
                # Warnings
                'stallwarning': xp.findDataRef("sim/flightmodel/failures/stallwarning"),
                'warn_overspeed': xp.findDataRef("sim/operation/prefs/warn_overspeed"),
                'warn_overspeed_flaps': xp.findDataRef("sim/operation/prefs/warn_overspeed_flaps"),
                'warn_overspeed_gear': xp.findDataRef("sim/operation/prefs/warn_overspeed_gear"),
                
                # Time
                'local_date_days': xp.findDataRef("sim/time/local_date_days"),
                'zulu_time_sec': xp.findDataRef("sim/time/zulu_time_sec"),
                'local_time_sec': xp.findDataRef("sim/time/local_time_sec"),
                
                # Weather
                'visibility_reported_m': xp.findDataRef("sim/weather/visibility_m"),
                
                # Pause state
                'paused': xp.findDataRef("sim/time/paused"),
            }
            
            # Aircraft configuration datarefs
            self.aircraft_datarefs = {
                'acf_en_type': xp.findDataRef("sim/aircraft/prop/acf_en_type"),
                'acf_num_engines': xp.findDataRef("sim/aircraft/engine/acf_num_engines"),
                'acf_Vs': xp.findDataRef("sim/aircraft/view/acf_Vs"),
                'acf_Vno': xp.findDataRef("sim/aircraft/view/acf_Vno"),
                'acf_Vne': xp.findDataRef("sim/aircraft/view/acf_Vne"),
                'acf_Vfe': xp.findDataRef("sim/aircraft/view/acf_Vfe"),
                'acf_m_max': xp.findDataRef("sim/aircraft/weight/acf_m_max"),
                'acf_m_empty': xp.findDataRef("sim/aircraft/weight/acf_m_empty"),
                'acf_m_fuel_tot': xp.findDataRef("sim/aircraft/weight/acf_m_fuel_tot"),
                'acf_tank_rat': xp.findDataRef("sim/aircraft/overflow/acf_tank_rat"),
            }
            
            xp.log(f"OnAir Company Plugin: Initialized {len(self.datarefs)} sim datarefs")
            xp.log(f"OnAir Company Plugin: Initialized {len(self.aircraft_datarefs)} aircraft datarefs")
            
        except Exception as e:
            xp.log(f"OnAir Company Plugin: Error in init_datarefs(): {e}")
        
        xp.log("OnAir Company Plugin: init_datarefs() completed")
    
    def get_sim_data(self) -> Dict[str, Any]:
        """Collect all simulation data safely"""
        data = {}

        def safe_get(key, func, default):
            ref = self.datarefs.get(key)
            if ref is None:
                return default
            try:
                return func(ref)
            except Exception as e:
                # Helpful for debugging which specific dataref is failing
                # xp.log(f"OnAir Company Plugin: Error getting {key}: {e}")
                return default
        
        try:
            # Basic flight data
            data['elevation'] = safe_get('elevation', xp.getDatad, 0.0)
            data['latitude'] = safe_get('latitude', xp.getDataf, 0.0)
            data['longitude'] = safe_get('longitude', xp.getDataf, 0.0)
            data['y_agl'] = safe_get('y_agl', xp.getDataf, 0.0)
            data['phi'] = safe_get('phi', xp.getDataf, 0.0)
            data['theta'] = safe_get('theta', xp.getDataf, 0.0)
            data['psi'] = safe_get('psi', xp.getDataf, 0.0)
            data['mag_psi'] = safe_get('mag_psi', xp.getDataf, 0.0)
            
            # Speed
            data['vh_ind'] = safe_get('vh_ind', xp.getDataf, 0.0)
            data['true_airspeed'] = safe_get('true_airspeed', xp.getDataf, 0.0)
            data['airspeed_kts'] = safe_get('airspeed_kts', xp.getDataf, 0.0)
            data['groundspeed'] = safe_get('groundspeed', xp.getDataf, 0.0)
            
            # Aircraft state
            data['onground_any'] = safe_get('onground_any', xp.getDatai, 0)
            data['has_crashed'] = safe_get('has_crashed', xp.getDatai, 0)
            data['autopilot_mode'] = safe_get('autopilot_mode', xp.getDatai, 0)
            
            # Altitude and forces
            data['altitude_ft'] = safe_get('altitude_ft', xp.getDataf, 0.0)
            data['gforce_normal'] = safe_get('gforce_normal', xp.getDataf, 1.0)
            
            data['m_fixed'] = safe_get('m_fixed', xp.getDataf, 0.0)
            data['num_tanks'] = safe_get('num_tanks', xp.getDatai, 0)
            
            # Fuel Weights (Array of 9 floats)
            m_fuel_ref = self.datarefs.get('m_fuel')
            if m_fuel_ref:
                # Create a buffer list of 9 zeros
                fuel_buffer = [0.0] * 9
                # X-Plane fills the buffer and returns the count of items filled
                xp.getDatavf(m_fuel_ref, fuel_buffer, 0, 9)
                data['m_fuel'] = fuel_buffer
            else:
                data['m_fuel'] = [0.0] * 9
            
            # Fuel Flow (Array of 8 floats)
            ff_ref = self.datarefs.get('fuel_flow')
            if ff_ref:
                ff_buffer = [0.0] * 8
                xp.getDatavf(ff_ref, ff_buffer, 0, 8)
                data['fuel_flow'] = ff_buffer
            else:
                data['fuel_flow'] = [0.0] * 8
                
            # Engines Burning/Running (Arrays of 8 ints)
            burn_ref = self.datarefs.get('engine_burning_fuel')
            if burn_ref:
                burn_buffer = [0] * 8
                xp.getDatavi(burn_ref, burn_buffer, 0, 8)
                data['engine_burning_fuel'] = burn_buffer
            else:
                data['engine_burning_fuel'] = [0] * 8

            # Engine Running
            run_ref = self.datarefs.get('engine_running')
            if run_ref:
                run_buffer = [0] * 8
                xp.getDatavi(run_ref, run_buffer, 0, 8)
                data['engine_running'] = run_buffer
            else:
                data['engine_running'] = [0] * 8

            # Fuel Pumps
            pump_ref = self.datarefs.get('fuel_pump_on')
            if pump_ref:
                pump_buffer = [0] * 8
                xp.getDatavi(pump_ref, pump_buffer, 0, 8)
                data['fuel_pump_on'] = pump_buffer
            else:
                data['fuel_pump_on'] = [0] * 8
            
            # Lights
            data['beacon_lights_on'] = safe_get('beacon_lights_on', xp.getDatai, 0)
            data['landing_lights_on'] = safe_get('landing_lights_on', xp.getDatai, 0)
            data['nav_lights_on'] = safe_get('nav_lights_on', xp.getDatai, 0)
            data['strobe_lights_on'] = safe_get('strobe_lights_on', xp.getDatai, 0)
            data['taxi_light_on'] = safe_get('taxi_light_on', xp.getDatai, 0)
            
            # Controls
            data['flap_handle_deploy_ratio'] = safe_get('flap_handle_deploy_ratio', xp.getDataf, 0.0)
            data['gear_handle_down'] = safe_get('gear_handle_down', xp.getDatai, 0)
            
            # Warnings
            data['stallwarning'] = safe_get('stallwarning', xp.getDatai, 0)
            data['warn_overspeed'] = safe_get('warn_overspeed', xp.getDatai, 0)
            data['warn_overspeed_flaps'] = safe_get('warn_overspeed_flaps', xp.getDatai, 0)
            data['warn_overspeed_gear'] = safe_get('warn_overspeed_gear', xp.getDatai, 0)
            
            # Time (XP12 expects Doubles for Zulu/Local time)
            data['local_date_days'] = safe_get('local_date_days', xp.getDatai, 0)
            data['zulu_time_sec'] = safe_get('zulu_time_sec', xp.getDataf, 0.0)
            data['local_time_sec'] = safe_get('local_time_sec', xp.getDataf, 0.0)
            
            # Weather
            data['visibility_reported_m'] = safe_get('visibility_reported_m', xp.getDataf, 16000.0)
            
            # Pause state
            data['paused'] = safe_get('paused', xp.getDatai, 0)
            
            # log data
            # xp.log(f"OnAir Company Plugin: Collected sim data: {data}")

            # Aircraft path logic
            try:
                aircraft_info = xp.getNthAircraftModel(0)
                data['aircraft_path'] = aircraft_info[1] if len(aircraft_info) > 1 else "Aircraft/Default/default.acf"
            except Exception as e:
                xp.log(f"OnAir Company Plugin: Error reading aircraft path: {e}")
                data['aircraft_path'] = "Aircraft/Default/default.acf"

        except Exception as e:
            xp.log(f"OnAir Company Plugin: Error in get_sim_data(): {e}")
            
        return data
    
    def get_aircraft_data(self) -> Dict[str, Any]:
        """Get aircraft configuration data"""
        data = {}
        
        try:

            # Engine types (Array of 8 ints)
            en_type_ref = self.aircraft_datarefs.get('acf_en_type')
            if en_type_ref:
                en_buffer = [0] * 8
                xp.getDatavi(en_type_ref, en_buffer, 0, 8)
                data['acf_en_type'] = en_buffer
            else:
                data['acf_en_type'] = [0] * 8

            # Tank ratios (Array of 9 floats)
            tank_rat_ref = self.aircraft_datarefs.get('acf_tank_rat')
            if tank_rat_ref:
                rat_buffer = [0.0] * 9
                xp.getDatavf(tank_rat_ref, rat_buffer, 0, 9)
                data['acf_tank_rat'] = rat_buffer
            else:
                data['acf_tank_rat'] = [0.0] * 9

            # Single value datarefs (These are fine)
            data['acf_num_engines'] = xp.getDatai(self.aircraft_datarefs['acf_num_engines'])
            data['acf_Vs'] = xp.getDataf(self.aircraft_datarefs['acf_Vs'])
            data['acf_Vno'] = xp.getDataf(self.aircraft_datarefs['acf_Vno'])
            data['acf_Vne'] = xp.getDataf(self.aircraft_datarefs['acf_Vne'])
            data['acf_Vfe'] = xp.getDataf(self.aircraft_datarefs['acf_Vfe'])
            data['acf_m_max'] = xp.getDataf(self.aircraft_datarefs['acf_m_max'])
            data['acf_m_empty'] = xp.getDataf(self.aircraft_datarefs['acf_m_empty'])
            data['acf_m_fuel_tot'] = xp.getDataf(self.aircraft_datarefs['acf_m_fuel_tot'])
            
            # log data
            # xp.log(f"OnAir Company Plugin: Collected ac data: {data}")
            
        except Exception as e:
            xp.log(f"OnAir Company: Error collecting aircraft data: {e}")
            
        return data
    
    def pack_onair_data(self, live_data, type_data, fuel_tanks, out_path) -> bytes:
        # Create a blank 4096-byte buffer
        buffer = bytearray(4096)

        # --- PACK XPlaneLiveAircraftStruct ---
        # Offsets calculated from your C code (index * 4)
        struct.pack_into("<i", buffer, 0 * 4, live_data['NumberOfTanks'])
        struct.pack_into("<i", buffer, 1 * 4, live_data['DateLocalDays'])
        struct.pack_into("<i", buffer, 2 * 4, live_data['PlaneOnGround'])
        struct.pack_into("<i", buffer, 3 * 4, live_data['HasCrashed'])
        struct.pack_into("<i", buffer, 4 * 4, live_data['AutoPilotMode'])
        
        # Elevation: Index 6 (Offset 24), 8-byte Double
        struct.pack_into("<d", buffer, 6 * 4, float(live_data['Elevation']))
        
        struct.pack_into("<f", buffer, 8 * 4, float(live_data['Latitude']))
        struct.pack_into("<f", buffer, 9 * 4, float(live_data['Longitude']))
        struct.pack_into("<f", buffer, 10 * 4, float(live_data['RadioAltitude']))
        struct.pack_into("<f", buffer, 11 * 4, float(live_data['VerticalSpeedMetersPerSecond']))
        struct.pack_into("<f", buffer, 12 * 4, float(live_data['Pitch']))
        struct.pack_into("<f", buffer, 13 * 4, float(live_data['Bank']))
        struct.pack_into("<f", buffer, 14 * 4, float(live_data['AltimeterAltitude']))
        struct.pack_into("<f", buffer, 15 * 4, float(live_data['GForce']))
        struct.pack_into("<f", buffer, 16 * 4, float(live_data['TrueAirSpeedMpS']))
        struct.pack_into("<f", buffer, 17 * 4, float(live_data['IndicatedAirSpeedKts']))
        struct.pack_into("<f", buffer, 18 * 4, float(live_data['GroundSpeedMpS']))
        struct.pack_into("<f", buffer, 19 * 4, float(live_data['PayloadWeightInKg']))
        struct.pack_into("<f", buffer, 20 * 4, float(live_data['HeadingTrue']))
        struct.pack_into("<f", buffer, 21 * 4, float(live_data['HeadingMagnetic']))
        struct.pack_into("<f", buffer, 22 * 4, float(live_data['DateUTCSeconds']))
        struct.pack_into("<f", buffer, 23 * 4, float(live_data['DateLocalSeconds']))

        # Arrays: Use a loop to match the C code's offset logic
        # Fuel Tanks Weights: Index 0x18 (24)
        for i, weight in enumerate(live_data['FuelTanksWeightsInKg'][:9]):
            struct.pack_into("<f", buffer, (24 + i) * 4, float(weight))

        # Engines FF: Index 0x21 (33)
        for i, ff in enumerate(live_data['EnginesFFInKgPSec'][:8]):
            struct.pack_into("<f", buffer, (33 + i) * 4, float(ff))

        # Engine Burning: Index 0x29 (41)
        for i, val in enumerate(live_data['EngineIsBurningFuel'][:8]):
            struct.pack_into("<i", buffer, (41 + i) * 4, int(val))

        # Engine Running: Index 0x31 (49)
        for i, val in enumerate(live_data['EngineIsRunning'][:8]):
            struct.pack_into("<i", buffer, (49 + i) * 4, int(val))

        # Flaps etc: Index 0x39 (57)
        struct.pack_into("<f", buffer, 57 * 4, float(live_data['FlapHandleDeployRatio']))
        struct.pack_into("<i", buffer, 58 * 4, int(live_data['GearHandleDown']))
        struct.pack_into("<i", buffer, 59 * 4, int(live_data['WarnOverspeedFlaps']))
        struct.pack_into("<i", buffer, 60 * 4, int(live_data['WarnOverspeedGear']))
        struct.pack_into("<i", buffer, 61 * 4, int(live_data['beacon_lights_on']))
        struct.pack_into("<i", buffer, 62 * 4, int(live_data['landing_lights_on']))
        struct.pack_into("<i", buffer, 63 * 4, int(live_data['nav_lights_on']))
        struct.pack_into("<i", buffer, 64 * 4, int(live_data['strobe_lights_on']))
        struct.pack_into("<i", buffer, 65 * 4, int(live_data['taxi_light_on']))

        # Fuel Pumps: Index 0x42 (66)
        for i, val in enumerate(live_data['fuel_pump_on'][:8]):
            struct.pack_into("<i", buffer, (66 + i) * 4, int(val))

        struct.pack_into("<i", buffer, 74 * 4, int(live_data['stallwarning']))
        struct.pack_into("<i", buffer, 75 * 4, int(live_data['warn_overspeed']))
        struct.pack_into("<f", buffer, 76 * 4, float(live_data['visibility_reported_m']))
        struct.pack_into("<i", buffer, 77 * 4, int(live_data['ground_speed']))
        struct.pack_into("<f", buffer, 78 * 4, float(live_data['wind_heading_deg_mag']))
        struct.pack_into("<f", buffer, 79 * 4, float(live_data['wind_speed_kts']))
        
        # Validation: Index 0x50 (80)
        struct.pack_into("<i", buffer, 80 * 4, 1234567890)

        # --- PACK XPlaneAircraftTypeStruct ---
        # Start offset: This begins immediately after the first struct.
        # The C# client does: numArray3 = new byte[Marshal.SizeOf(typeof(XPlaneAircraftTypeStruct))]
        # Based on the slots above, the first struct is 81 slots (324 bytes).
        # However, Marshal.SizeOf(LiveStruct) is likely 328 due to 8-byte alignment.
        TYPE_START = 328

        struct.pack_into("<i", buffer, TYPE_START + 0, int(type_data['EngineType']))
        struct.pack_into("<i", buffer, TYPE_START + 4, int(type_data['NumberOfEngines']))
        struct.pack_into("<f", buffer, TYPE_START + 8, float(type_data['DesignSpeedVS0']))
        struct.pack_into("<f", buffer, TYPE_START + 12, float(type_data['DesignSpeedVC']))
        struct.pack_into("<f", buffer, TYPE_START + 16, float(type_data['DesignSpeedVne']))
        struct.pack_into("<f", buffer, TYPE_START + 20, float(type_data['DesignSpeedVfe']))
        struct.pack_into("<f", buffer, TYPE_START + 24, float(type_data['MaximumGrossWeightInKg']))
        struct.pack_into("<f", buffer, TYPE_START + 28, float(type_data['EmptyWeightInKg']))

        # Fuel Tank Array (9 * 8 bytes)
        for i in range(9):
            offset = TYPE_START + 32 + (i * 8)
            cap = fuel_tanks[i]['CapacityInKg'] if i < len(fuel_tanks) else 0.0
            order = fuel_tanks[i]['SimOrder'] if i < len(fuel_tanks) else 0
            struct.pack_into("<fi", buffer, offset, cap, order)

        # Aircraft Path (512 bytes)
        path_bytes = out_path.encode('utf-8')[:511]
        for i, b in enumerate(path_bytes):
            buffer[TYPE_START + 104 + i] = b

        return bytes(buffer)
        
    def pack_data(self, sim_data: Dict[str, Any], aircraft_data: Dict[str, Any]) -> bytes:
        """Pack data into binary format using manual struct.pack to avoid ctypes alignment issues"""
        
        # Use lock to prevent race conditions
        with self._pack_lock:
            # Validate input data first
            if not sim_data or not aircraft_data:
                xp.log("OnAir Company: Invalid input data, returning empty packet")
                return b'\x00' * 1500
                
            try:
                
                # Basic fields with validation
                num_tanks = max(0, min(9, int(sim_data.get('num_tanks', 2))))
                date_local_days = max(0, min(999999, int(sim_data.get('local_date_days', 89))))
                plane_on_ground = 1 if sim_data.get('onground_any', 0) else 0
                has_crashed = 1 if sim_data.get('has_crashed', 0) else 0
                autopilot_mode = max(0, min(10, int(sim_data.get('autopilot_mode', 0))))
                
                # Elevation with sanity check
                elevation = float(sim_data.get('elevation', 0.0))
                if abs(elevation) > 50000 or elevation != elevation:
                    elevation = 0.0
                
                # Position and motion with sanity checks
                lat = float(sim_data.get('latitude', 37.5))
                if abs(lat) > 90 or lat != lat:
                    lat = 37.5
                
                lon = float(sim_data.get('longitude', -122.0))
                if abs(lon) > 180 or lon != lon:
                    lon = -122.0
                
                radio_alt = float(sim_data.get('y_agl', 0.0))
                if radio_alt < -1000 or radio_alt > 100000 or radio_alt != radio_alt:
                    radio_alt = 0.0
                
                vs = float(sim_data.get('vh_ind', 0.0))
                if abs(vs) > 1000 or vs != vs:
                    vs = 0.0
                
                pitch = float(sim_data.get('theta', 0.0))
                if abs(pitch) > 1.6 or pitch != pitch:
                    pitch = 0.0
                
                bank = float(sim_data.get('phi', 0.0))
                if abs(bank) > 3.2 or bank != bank:
                    bank = 0.0
                
                alt = float(sim_data.get('altitude_ft', 0.0))
                if alt < -1000 or alt > 100000 or alt != alt:
                    alt = 0.0
                
                gforce = float(sim_data.get('gforce_normal', 1.0))
                if gforce < -10 or gforce > 20 or gforce != gforce:
                    gforce = 1.0
                
                tas = float(sim_data.get('true_airspeed', 0.0))
                if tas < 0 or tas > 1000 or tas != tas:
                    tas = 0.0
                
                ias = float(sim_data.get('airspeed_kts', 0.0))
                if ias < 0 or ias > 2000 or ias != ias:
                    ias = 0.0
                
                gs = float(sim_data.get('groundspeed', 0.0))
                if gs < 0 or gs > 1000 or gs != gs:
                    gs = 0.0
                
                payload = float(sim_data.get('m_fixed', 0.0))
                if payload < 0 or payload > 100000 or payload != payload:
                    payload = 0.0
                
                hdg_true = float(sim_data.get('psi', 0.0))
                if hdg_true < 0 or hdg_true > 6.3 or hdg_true != hdg_true:
                    hdg_true = 0.0
                
                hdg_mag = float(sim_data.get('mag_psi', 0.0))
                if hdg_mag < 0 or hdg_mag > 6.3 or hdg_mag != hdg_mag:
                    hdg_mag = 0.0
                
                utc_sec = float(sim_data.get('zulu_time_sec', 43200.0))
                if utc_sec < 0 or utc_sec > 86400 or utc_sec != utc_sec:
                    utc_sec = 43200.0
                
                local_sec = float(sim_data.get('local_time_sec', 43200.0))
                if local_sec < 0 or local_sec > 86400 or local_sec != local_sec:
                    local_sec = 43200.0
                
                # Fuel arrays - ensure we have valid fuel data
                fuel_weights = sim_data.get('m_fuel', [100.0, 50.0] + [0.0] * 7)
                fuel_array = []
                for i in range(9):
                    fuel = fuel_weights[i] if i < len(fuel_weights) else 0.0
                    if fuel < 0 or fuel > 50000 or fuel != fuel:
                        fuel = 0.0
                    fuel_array.append(fuel)
                
                # Engine arrays - sanitize all values
                engine_ff = sim_data.get('fuel_flow', [0.0] * 8)
                engine_burning = sim_data.get('engine_is_burning_fuel', [0] * 8)
                engine_running = sim_data.get('engine_running', [0] * 8)
                fuel_pump = sim_data.get('fuel_pump_on', [0] * 8)
                
                engine_ff_array = []
                engine_burning_array = []
                engine_running_array = []
                fuel_pump_array = []
                
                for i in range(8):
                    # Fuel flow with validation
                    ff = engine_ff[i] if i < len(engine_ff) else 0.0
                    if ff < 0 or ff > 10 or ff != ff:
                        ff = 0.0
                    engine_ff_array.append(ff)
                    
                    # Engine states as integers (0 or 1)
                    engine_burning_array.append(1 if (i < len(engine_burning) and engine_burning[i]) else 0)
                    engine_running_array.append(1 if (i < len(engine_running) and engine_running[i]) else 0)
                    fuel_pump_array.append(1 if (i < len(fuel_pump) and fuel_pump[i]) else 0)
                
                # Control surfaces and lights
                flap_ratio = float(sim_data.get('flap_handle_deploy_ratio', 0.0))
                if flap_ratio < 0 or flap_ratio > 1 or flap_ratio != flap_ratio:
                    flap_ratio = 0.0
                
                gear_down = 1 if sim_data.get('gear_handle_down', 0) else 0
                warn_flaps = 1 if sim_data.get('warn_overspeed_flaps', 0) else 0
                warn_gear = 1 if sim_data.get('warn_overspeed_gear', 0) else 0
                beacon_on = 1 if sim_data.get('beacon_lights_on', 0) else 0
                landing_on = 1 if sim_data.get('landing_lights_on', 0) else 0
                nav_on = 1 if sim_data.get('nav_lights_on', 0) else 0
                strobe_on = 1 if sim_data.get('strobe_lights_on', 0) else 0
                taxi_on = 1 if sim_data.get('taxi_light_on', 0) else 0
                
                # Warnings and weather
                stall_warn = 1 if sim_data.get('stallwarning', 0) else 0
                overspeed_warn = 1 if sim_data.get('warn_overspeed', 0) else 0
                
                vis = float(sim_data.get('visibility_reported_m', 10000.0))
                if vis < 0 or vis > 100000 or vis != vis:
                    vis = 10000.0
                
                ground_speed = max(0, min(1000, int(sim_data.get('groundspeed', 0))))
                
                wind_hdg = float(sim_data.get('wind_heading_deg_mag', 0.0))
                if wind_hdg < 0 or wind_hdg > 360 or wind_hdg != wind_hdg:
                    wind_hdg = 0.0
                
                wind_speed = float(sim_data.get('wind_speed_kts', 0.0))
                if wind_speed < 0 or wind_speed > 200 or wind_speed != wind_speed:
                    wind_speed = 0.0
                
                # CRITICAL: Validation field - this MUST be 1234567890
                validation = 1234567890
                
                live_data = {
                    'NumberOfTanks': num_tanks,
                    'DateLocalDays': date_local_days,
                    'PlaneOnGround': plane_on_ground,
                    'HasCrashed': has_crashed,
                    'AutoPilotMode': autopilot_mode,
                    'Elevation': elevation,
                    'Latitude': lat,
                    'Longitude': lon,
                    'RadioAltitude': radio_alt,
                    'VerticalSpeedMetersPerSecond': vs,
                    'Pitch': pitch,
                    'Bank': bank,
                    'AltimeterAltitude': alt,
                    'GForce': gforce,
                    'TrueAirSpeedMpS': tas,
                    'IndicatedAirSpeedKts': ias,
                    'GroundSpeedMpS': ground_speed,
                    'PayloadWeightInKg': payload,
                    'HeadingTrue': hdg_true,
                    'HeadingMagnetic': hdg_mag,
                    'DateUTCSeconds': utc_sec,
                    'DateLocalSeconds': local_sec,
                    
                    # These MUST be lists of the size defined in XPlaneLiveAircraftStruct.cs
                    'FuelTanksWeightsInKg': fuel_array,  # List of 9 floats
                    'EnginesFFInKgPSec': engine_ff_array,     # List of 8 floats
                    'EngineIsBurningFuel': engine_burning_array,      # List of 8 ints
                    'EngineIsRunning': engine_running_array,          # List of 8 ints
                    
                    'FlapHandleDeployRatio': flap_ratio,
                    'GearHandleDown': gear_down,
                    'WarnOverspeedFlaps': warn_flaps,
                    'WarnOverspeedGear': warn_gear,
                    'beacon_lights_on': beacon_on,
                    'landing_lights_on': landing_on,
                    'nav_lights_on': nav_on,
                    'strobe_lights_on': strobe_on,
                    'taxi_light_on': taxi_on,
                    'fuel_pump_on': fuel_pump,
                    'stallwarning': stall_warn,
                    'warn_overspeed': overspeed_warn,
                    'visibility_reported_m': vis,
                    'ground_speed': ground_speed,
                    'wind_heading_deg_mag': wind_hdg,
                    'wind_speed_kts': wind_speed,
                    'Validation': validation
                }

            except Exception as e:
                xp.log(f"OnAir Company: Error packing live struct: {e}")
                import traceback
                xp.log(f"OnAir Company: Traceback: {traceback.format_exc()}")
                return b'\x00' * 1500
            
            try:
                # Pack XPlaneAircraftTypeStruct manually
                
                # Aircraft configuration with validation
                engine_types = aircraft_data.get('acf_en_type', [5])
                engine_type = engine_types[0] if engine_types else 5
                num_engines = max(0, min(8, int(aircraft_data.get('acf_num_engines', 2))))
                
                vs0 = float(aircraft_data.get('acf_Vs', 60.0))
                if vs0 < 0 or vs0 > 500 or vs0 != vs0:
                    vs0 = 60.0
                
                vno = float(aircraft_data.get('acf_Vno', 150.0))
                if vno < 0 or vno > 1000 or vno != vno:
                    vno = 150.0
                
                vne = float(aircraft_data.get('acf_Vne', 200.0))
                if vne < 0 or vne > 1000 or vne != vne:
                    vne = 200.0
                
                vfe = float(aircraft_data.get('acf_Vfe', 100.0))
                if vfe < 0 or vfe > 500 or vfe != vfe:
                    vfe = 100.0
                
                max_weight = float(aircraft_data.get('acf_m_max', 2000.0))
                if max_weight < 0 or max_weight > 1000000 or max_weight != max_weight:
                    max_weight = 2000.0
                
                empty_weight = float(aircraft_data.get('acf_m_empty', 1200.0))
                if empty_weight < 0 or empty_weight > 1000000 or empty_weight != empty_weight:
                    empty_weight = 1200.0
                
                # Fuel tank configuration
                total_fuel = float(aircraft_data.get('acf_m_fuel_tot', 400.0))
                if total_fuel < 0 or total_fuel > 100000 or total_fuel != total_fuel:
                    total_fuel = 400.0
                    
                tank_ratios = aircraft_data.get('acf_tank_rat', [0.5, 0.5] + [0.0] * 7)
                tank_capacities = []
                tank_orders = []
                for i in range(9):
                    ratio = tank_ratios[i] if i < len(tank_ratios) else 0.0
                    if ratio < 0 or ratio > 1 or ratio != ratio:
                        ratio = 0.0
                    tank_capacities.append(total_fuel * ratio)
                    tank_orders.append(i)
                
                # Aircraft path
                aircraft_path = sim_data.get('aircraft_path', "Aircraft/Default/default.acf")
                if aircraft_path and not aircraft_path.startswith("Aircraft/"):
                    aircraft_path = f"Aircraft/Laminar Research/Cessna 172 SP/{aircraft_path}"
                
                # Prepare tank data
                tank_data = [
                    {'CapacityInKg': tank_capacities[0], 'SimOrder': tank_orders[0]},
                    {'CapacityInKg': tank_capacities[1], 'SimOrder': tank_orders[1]},
                    {'CapacityInKg': tank_capacities[2], 'SimOrder': tank_orders[2]},
                    {'CapacityInKg': tank_capacities[3], 'SimOrder': tank_orders[3]},
                    {'CapacityInKg': tank_capacities[4], 'SimOrder': tank_orders[4]},
                    {'CapacityInKg': tank_capacities[5], 'SimOrder': tank_orders[5]},
                    {'CapacityInKg': tank_capacities[6], 'SimOrder': tank_orders[6]},
                    {'CapacityInKg': tank_capacities[7], 'SimOrder': tank_orders[7]},
                    {'CapacityInKg': tank_capacities[8], 'SimOrder': tank_orders[8]}
                ]
                
                type_data = {
                    'EngineType': engine_type,
                    'NumberOfEngines': num_engines,
                    'DesignSpeedVS0': vs0,
                    'DesignSpeedVC': vno,
                    'DesignSpeedVne': vne,
                    'DesignSpeedVfe': vfe,
                    'MaximumGrossWeightInKg': max_weight,
                    'EmptyWeightInKg': empty_weight
                }

                # log livedata typedata tankdata and path for debugging
                # xp.log(f"Live Data: {live_data}")
                # xp.log(f"Type Data: {type_data}")
                # xp.log(f"Tank Data: {tank_data}")
                # xp.log(f"Aircraft Path: {aircraft_path}")

                # Combine both structs
                packet = self.pack_onair_data(live_data, type_data, tank_data, aircraft_path)
                
                # Validate final packet
                if len(packet) < 500:
                    xp.log(f"OnAir Company: Packet too small ({len(packet)} bytes), aborting")
                    return b'\x00' * 1500
                
                # xp.log(f"OnAir Company: Successfully created packet of {len(packet)} bytes")
                return packet
            
            except Exception as e:
                xp.log(f"OnAir Company: Error packing type struct: {e}")
                import traceback
                xp.log(f"OnAir Company: Traceback: {traceback.format_exc()}")
                return b'\x00' * 1500

    def connect(self):
        """Connect to OnAir client"""
        if self.connected:
            return True
            
        try:
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.socket.settimeout(5.0)
            self.socket.connect((self.server_ip, self.server_port))
            self.connected = True
            self.connection_status = "Connected"
            self.status_color = [0.0, 1.0, 0.0]  # Green
            return True
        except Exception as e:
            self.connected = False
            self.connection_status = f"Connection failed: {e}"
            self.status_color = [1.0, 0.0, 0.0]  # Red
            # xp.log(f"OnAir Company Plugin: Connection failed: {e}")
            if self.socket:
                self.socket.close()
                self.socket = None
            return False
    
    def disconnect(self):
        """Disconnect from OnAir client"""
        xp.log("OnAir Company Plugin: disconnect() called")
        
        if self.socket:
            try:
                self.socket.close()
                xp.log("OnAir Company Plugin: Socket closed successfully")
            except:
                xp.log("OnAir Company Plugin: Error closing socket")
                pass
            self.socket = None
        self.connected = False
        self.connection_status = "Disconnected"
        self.status_color = [1.0, 1.0, 1.0]  # White
    
    def send_data(self, data: bytes) -> bool:
        """Send data to OnAir client"""
        if not self.connected or not self.socket:
            return False
            
        try:
            # Keep socket alive options to prevent polling disconnections
            if not hasattr(self, 'socket_configured'):
                try:
                    self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
                    # Set TCP_NODELAY to send immediately
                    self.socket.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                    self.socket_configured = True
                except Exception:
                    pass  # Ignore socket option errors
            
            self.socket.send(data)
            return True
        except socket.error as e:
            if e.errno == errno.EPIPE:
                xp.log("OnAir Company: Connection broken (EPIPE) - client disconnected during poll")
            elif e.errno in (errno.ECONNRESET, errno.ENOTCONN):
                xp.log("OnAir Company: Connection reset by client during polling")
            else:
                xp.log(f"OnAir Company: Socket error: {e}")
            self.disconnect()
            return False
        except Exception as e:
            xp.log(f"OnAir Company Plugin: Send error: {e}")
            self.disconnect()
            return False
    
    def check_paused(self):
        """Check if sim is paused and handle external control"""
        with self._file_lock:
            try:
                # Check for external pause control file
                pause_file = os.path.join(self.plugin_dir, "write_pause.oair")
                if os.path.exists(pause_file):
                    with open(pause_file, 'rb') as f:
                        # Read XPlaneWritePauseStruct: 1 byte for bool
                        data = f.read(1)
                        if len(data) >= 1:
                            should_pause = struct.unpack('<B', data)[0] != 0
                            current_paused = xp.getDatai(self.datarefs['paused']) != 0
                            
                            if should_pause != current_paused:
                                # Use the proper X-Plane pause toggle command
                                pause_cmd = xp.findCommand("sim/operation/pause_toggle")
                                if pause_cmd is not None:
                                    xp.commandOnce(pause_cmd)
                            
                            # Remove file after processing
                            os.remove(pause_file)
            except Exception as e:
                xp.log(f"OnAir Company: Error checking pause: {e}")
    
    def set_datetime(self):
        """Set sim date/time from external file"""
        with self._file_lock:
            try:
                datetime_file = os.path.join(self.plugin_dir, "write_date.oair")
                if os.path.exists(datetime_file):
                    with open(datetime_file, 'rb') as f:
                        # Read XPlaneWriteDateStruct: float DateZuluSeconds + int DateDays = 8 bytes
                        data = f.read(8)
                        if len(data) >= 8:
                            zulu_time, local_days = struct.unpack('<fi', data)
                            
                            xp.setDataf(self.datarefs['zulu_time_sec'], zulu_time)
                            xp.setDatai(self.datarefs['local_date_days'], local_days)
                            
                            # Remove file after processing
                            os.remove(datetime_file)
            except Exception as e:
                xp.log(f"OnAir Company: Error setting datetime: {e}")
    
    def set_fuel(self):
        """Set fuel quantities from external file"""
        with self._file_lock:
            try:
                fuel_file = os.path.join(self.plugin_dir, "write_fuel.oair")
                if os.path.exists(fuel_file):
                    with open(fuel_file, 'rb') as f:
                        # Read XPlaneWriteFuelStruct: 9 floats = 36 bytes
                        data = f.read(36)
                        if len(data) >= 36:
                            fuel_values = list(struct.unpack('<9f', data))
                            xp.log(f"OnAir Company: Setting fuel values: {fuel_values}")
                            xp.setDatavf(self.datarefs['m_fuel'], fuel_values, 0, len(fuel_values))
                            
                            # Remove file after processing
                            os.remove(fuel_file)
            except Exception as e:
                xp.log(f"OnAir Company: Error setting fuel: {e}")
    
    def set_weight(self):
        """Set aircraft weight from external file"""
        with self._file_lock:
            try:
                weight_file = os.path.join(self.plugin_dir, "write_payload.oair")
                if os.path.exists(weight_file):
                    with open(weight_file, 'rb') as f:
                        # Read XPlaneWritePayloadStruct: 1 float = 4 bytes
                        data = f.read(4)
                        if len(data) >= 4:
                            weight = struct.unpack('<f', data)[0]
                            xp.setDataf(self.datarefs['m_fixed'], weight)
                            
                            # Remove file after processing
                            os.remove(weight_file)
            except Exception as e:
                xp.log(f"OnAir Company: Error setting weight: {e}")
    
    def set_position(self):
        """Set aircraft position from external file"""
        with self._file_lock:
            try:
                position_file = os.path.join(self.plugin_dir, "write_position.oair")
                if os.path.exists(position_file):
                    with open(position_file, 'rb') as f:
                        # Read XPlaneWritePositionStruct: 4 floats (Latitude, Longitude, Heading, Altitude) = 16 bytes
                        data = f.read(16)
                        if len(data) >= 16:
                            latitude, longitude, heading, altitude = struct.unpack('<4f', data)
                            
                            # Set position data
                            xp.setDatad(self.datarefs['latitude'], latitude)
                            xp.setDatad(self.datarefs['longitude'], longitude)
                            xp.setDataf(self.datarefs['psi'], heading)
                            if altitude > 0:  # Only set altitude if provided
                                xp.setDatad(self.datarefs['elevation'], altitude)
                            
                            # Remove file after processing
                            os.remove(position_file)
            except Exception as e:
                xp.log(f"OnAir Company: Error setting position: {e}")
    
    def flight_loop_callback(self, elapsed_since_last_call, elapsed_time_since_last_flightloop, counter, refcon):
        """Main flight loop callback"""
        
        try:
            # Check for external control files
            self.check_paused()
            self.set_datetime()
            self.set_weight()
            self.set_fuel()
            self.set_position()
            
            # Connect if not connected
            if not self.connected:
                self.connect()
            
            # Send data if connected
            if self.connected:
                sim_data = self.get_sim_data()
                aircraft_data = self.get_aircraft_data()
                
                if sim_data and aircraft_data:
                    packet = self.pack_data(sim_data, aircraft_data)
                    if not self.send_data(packet):
                        self.connection_status = "Send failed"
                        self.status_color = [1.0, 1.0, 0.0]  # Yellow
        
        except Exception as e:
            xp.log(f"OnAir Company Plugin: Flight loop error: {e}")
            
        return 0.05
    
    def draw_callback(self, phase, is_before, refcon):
        """Draw status information"""
        try:
            current_time = time.time()
            
            # Check for new status message files
            status_files = [
                ("draw_text_info.txt", [1.0, 1.0, 1.0]),
                ("draw_text_success.txt", [0.0, 1.0, 0.0]),
                ("draw_text_warning.txt", [1.0, 1.0, 0.0]),
                ("draw_text_error.txt", [1.0, 0.0, 0.0]),
            ]
            
            # Check for new status files and read/delete them
            with self._file_lock:
                for filename, file_color in status_files:
                    filepath = os.path.join(self.plugin_dir, filename)
                    if os.path.exists(filepath):
                        try:
                            with open(filepath, 'r') as f:
                                new_message = f.read().strip()
                            
                            # Delete the file after reading
                            os.remove(filepath)
                            
                            # Update current status message if not empty
                            if new_message:
                                self.current_status_message = new_message
                                self.current_status_color = file_color
                                self.status_message_expires = current_time + 5.0  # Display for 5 seconds
                            break
                        except:
                            continue
            
            # Determine what message to display
            if current_time < self.status_message_expires and self.current_status_message:
                message = self.current_status_message
                color = self.current_status_color
            else:
                # Status message expired or no message, show connection status
                message = self.connection_status
                color = self.status_color
                # Clear expired message
                if current_time >= self.status_message_expires:
                    self.current_status_message = ""
            
            # Draw the status message
            xp.drawString(color, 300, 120, message, None, xp.Font_Proportional)
            
        except Exception as e:
            # Silently handle draw errors to avoid log spam
            pass
        
        return 1


# Global plugin instance - this is the interface XPPython3 expects
plugin_instance = PythonInterface()
