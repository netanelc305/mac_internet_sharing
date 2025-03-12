# Mac Internet Sharing

A Python CLI tool to manage internet sharing on macOS.

## Installation

```bash
pipx install mac-internet-sharing
```

## Usage

The tool provides several commands to manage internet sharing. Here are some common use cases:

### Starting Internet Sharing

To share your internet connection on a specified primary interface, use:

```bash
sudo misha configure -n <primary_interface> -u <udid> -u <udid> -s
```

- **`<primary_interface>`:** Replace with your network interface name (e.g., `"Ethernet Adapter (en6)"`).
- **`-u <udid>`:** Optionally specify one or more device UDIDs.
- **`-s`:** Automatically start sharing after configuration.

> **Note:** Newly connected devices after the initial setup are not added automatically you will need to reconfigure.

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

