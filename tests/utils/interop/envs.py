import os
import pathlib

from libp2p.utils.paths import get_binary_path

# Use the new cross-platform binary path function with fallback
try:
    GO_BIN_PATH = get_binary_path("GOPATH", "go")
except KeyError:
    # Fallback to default Go installation path if GOPATH is not set
    if os.name == 'nt':  # Windows
        GO_BIN_PATH = pathlib.Path("C:/Go/bin")
    else:  # Unix-like
        GO_BIN_PATH = pathlib.Path("/usr/local/go/bin")
