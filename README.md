# OnAir Company X-Plane Plugin

This project provides an X-Plane plugin that enables communication between X-Plane and the OnAir Company flight simulation platform on macOS. The plugin facilitates real-time flight data exchange and remote aircraft control.

## Overview

The OnAir Company X-Plane Plugin consists of:
- **Python Plugin** (`PI_OnAirCompany.py`) - XPPython3-based plugin that runs inside X-Plane
- **TCP Communication** - Real-time aircraft data streaming to OnAir Company client
- **File-based Commands** - Binary file I/O for receiving commands from OnAir (position, fuel, weight, pause, messages)

## Features

- Real-time aircraft telemetry streaming (position, attitude, speed, fuel, etc.)
- Remote aircraft positioning and parameter control
- Pause/unpause simulation control
- Status message display in X-Plane cockpit
- Automatic file cleanup and 5-second message display timer

## Prerequisites

- **X-Plane 12** (or X-Plane 11)
- **XPPython3 Plugin** 
- **OnAir Company Client** running in Wine/Codeweavers
- **macOS** (tested on macOS)

## Installation Guide

### 1. Install XPPython3

XPPython3 enables Python plugins in X-Plane.

#### Method A: Download from GitHub
1. Go to [https://github.com/pbuckner/x-plane_plugins/releases](https://github.com/pbuckner/x-plane_plugins/releases)
2. Download the latest `XPPython3-*.zip` file
3. Extract the archive
4. Copy the `XPPython3` folder to your X-Plane plugins directory:
   ```
   /Applications/X-Plane 12/Resources/plugins/XPPython3/
   ```

#### Method B: Using pip (if you have Python 3.8+)
```bash
pip3 install XPPython3
```

### 2. Install OnAir Company Client with Wine/Codeweavers

#### Option A: Codeweavers CrossOver (Recommended)
1. Install [Codeweavers CrossOver](https://www.codeweavers.com/crossover)
2. Create a new Windows 10 bottle
3. Download and install OnAir Company client in the bottle
4. Configure the client to use local networking (`127.0.0.1`)

#### Option B: Wine (Free Alternative)
1. Install Wine via Homebrew:
   ```bash
   brew install wine
   ```
2. Create a Wine prefix:
   ```bash
   export WINEPREFIX=$HOME/.wine-onair
   winecfg
   ```
3. Install OnAir Company client:
   ```bash
   wine setup.exe
   ```

### 3. Install the Python Plugin

1. Copy the Python plugin file to your XPPython3 plugins folder:
   ```bash
   cp PI_OnAirCompany.py "/Applications/X-Plane 12/Resources/plugins/PythonPlugins/"
   ```

## Configuration

### OnAir Company Client Configuration

1. Start the OnAir Company client in Wine/Codeweavers
2. In OnAir settings, configure:
   - **Simulator**: X-Plane
   - **Connection**: Local connection
   - **X-Plane Directory**: Set to your X-Plane directory
   - **Remote Computer**: Leave this un-checked
3. Use OnAir to install the plugin files to the X-Plane plugins directory (the plugin will create the necessary `OnAir.XPlanePlugin` folder and files)

## Usage

1. **Start X-Plane** - The plugin will automatically load and appear in the Plugin menu
2. **Start OnAir Company client** in Wine/Codeweavers
3. **Create/Load a flight** in OnAir Company
4. **Load your aircraft** in X-Plane
5. The plugin will automatically connect and begin streaming data

### Status Messages

The plugin displays status information in the X-Plane cockpit:
- **White text**: General information
- **Green text**: Success messages  
- **Yellow text**: Warning messages
- **Red text**: Error messages

Messages from OnAir Company are displayed for 5 seconds, then the display returns to showing connection status.

### Remote Commands

The OnAir Company client can remotely control X-Plane through binary files:
- **Position Control**: `write_position.oair` - Sets aircraft lat/lon/heading/altitude
- **Fuel Control**: `write_fuel.oair` - Sets fuel quantities for all tanks
- **Weight Control**: `write_payload.oair` - Sets aircraft payload weight
- **Pause Control**: `write_pause.oair` - Pauses/unpauses the simulation
- **Date/Time Control**: `write_date.oair` - Sets simulation date and time

## Troubleshooting

### Plugin Not Loading
- Check that XPPython3 is properly installed
- Verify `PI_OnAirCompany.py` is in the `PythonPlugins` folder
- Check X-Plane Log.txt for Python errors

### Connection Issues
- Verify OnAir Company client is running
- Check firewall settings (allow port 43230)
- Ensure `server_ip.txt` and `server_port.txt` are configured correctly
- Check that Wine/Codeweavers can access localhost networking

### OnAir Company Not Detecting X-Plane
- Ensure "Remote Computer" is un-checked in OnAir settings
- Verify X-Plane directory path is correctly set in OnAir (may need Wine drive mapping)
- Make sure the plugin directory structure exists

## Development

The plugin is written in Python 3 and uses:
- **XPPython3** for X-Plane integration
- **struct module** for binary data parsing
- **socket module** for TCP communication
- **threading** for network operations

### Building/Testing
```bash
# Syntax check
python3 -m py_compile PI_OnAirCompany.py

# Install in X-Plane
cp PI_OnAirCompany.py "/Applications/X-Plane 12/Resources/plugins/PythonPlugins/"
```

## License

This project is designed to work with OnAir Company's flight simulation platform. Please ensure you have appropriate licenses for OnAir Company, X-Plane, and any Wine/Codeweavers software used.

## Support

For issues related to:
- **X-Plane**: Check Laminar Research forums
- **XPPython3**: Check the [XPPython3 GitHub repository](https://github.com/pbuckner/x-plane_plugins)
- **OnAir Company**: Check OnAir Company support channels
- **Wine/Codeweavers**: Check respective support resources