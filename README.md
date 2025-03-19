# Mac Internet Sharing

A Python CLI tool to manage internet sharing on macOS.

## Installation

```bash
pipx install mac-internet-sharing
```

## Usage

The tool provides several commands to manage internet sharing. Here are some common use cases:

### Starting Internet Sharing

There are two methods to start internet sharing:

#### 1. Manual Configuration (`configure`)

This method requires you to manually specify the primary network interface and one or more device UDIDs. It sets up
internet sharing based on your initial configuration. Note that newly connected USB devices after the initial setup are
not added automatically—you will need to re-run the command to update the configuration.

```bash
sudo misha configure -n <primary_interface> -u <udid> -u <udid> -s
```

- **`<primary_interface>`:** Replace with your network interface name (e.g., `"Ethernet Adapter (en6)"`).
- **`-u <udid>`:** Optionally specify one or more device UDIDs.
- **`-s`:** Automatically start sharing after configuration.

#### 2. Automatic USB Detection (`plug-n-share`)

This method continuously monitors for new USB devices and automatically updates the sharing configuration when a new
device is detected. It is ideal if you frequently plug in different devices and want your sharing setup to update in
real time. You can also run it as a daemon.

```bash
sudo misha plug-n-share -n <primary_interface> -t <timeout>
```

- **`<primary_interface>` (optional):** Specify the network service name. If not provided, the default network service
  is used.
- **`-t <timeout>`:** Set the polling interval in seconds (default is 5 seconds).

> **Note:** The manual configuration (`configure`) does not automatically detect newly connected devices after the
> initial setup. Use `plug-n-share` if you require automatic updates.

### Toggling Internet Sharing

Manage the sharing state with the following commands:

- **Turn Sharing Off:**
  ```bash
  sudo misha off
  ```

- **Turn Sharing On:**
  ```bash
  sudo misha on
  ```

## Contributing

Contributions, bug reports, and feature requests are welcome!
Feel free to open issues or submit pull requests.

