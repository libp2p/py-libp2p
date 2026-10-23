#!/bin/bash
# Setup script for py-libp2p development environment
# This script handles the installation of development dependencies using PEP 735 dependency-groups

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}Setting up py-libp2p development environment...${NC}"

# Security: the eMudhra/emSign CA incident (October 2026) requires patched
# package managers, because pip and uv load their own bundled CA store in
# addition to the system one. See https://discuss.python.org/t/109576
MIN_UV_VERSION="0.13.4"
MIN_PIP_VERSION="26.2.2"

version_ge() {
    # usage: version_ge <actual> <minimum>; succeeds when actual >= minimum
    python3 -c '
import sys

def parts(version):
    return tuple(int(part) for part in version.split(".") if part.isdigit())

actual, minimum = parts(sys.argv[1]), parts(sys.argv[2])
sys.exit(0 if actual >= minimum else 1)
' "$1" "$2"
}

# Check if uv is available
if command -v uv &> /dev/null; then
    echo -e "${GREEN}Using uv for installation (recommended)...${NC}"
    UV_VERSION=$(uv --version | awk '{print $2}')
    if ! version_ge "$UV_VERSION" "$MIN_UV_VERSION"; then
        echo -e "${YELLOW}uv ${UV_VERSION} trusts the compromised eMudhra/emSign CA certificates; upgrading to >= ${MIN_UV_VERSION}...${NC}"
        UV_SYSTEM_CERTS=true uv self update || {
            echo -e "${RED}Could not upgrade uv automatically. Reinstall it with:${NC}"
            echo -e "  curl -LsSf https://astral.sh/uv/install.sh | sh"
            exit 1
        }
    fi
    # if on macOS, add gmp flags to the sync command
    if [[ "$(uname -s)" == "Darwin" ]]; then
        CFLAGS="$(pkg-config --cflags gmp)" LDFLAGS="$(pkg-config --libs gmp)" uv sync --group dev
    else
        uv sync --group dev
    fi

    # Install pre-commit hooks
    echo -e "${GREEN}Installing pre-commit hooks...${NC}"
    uv run pre-commit install

    echo -e "${GREEN}Setup complete! You can now run 'make pr' to check your changes, or 'make docs' to build the docs.${NC}"
else
    # Check if virtual environment flag is set
    if [[ -z "$VIRTUAL_ENV" ]]; then
        echo -e "${YELLOW}Warning: Not in a virtual environment. Creating one...${NC}"
        python3 -m venv .venv
        echo -e "${GREEN}Virtual environment created. Activate it with:${NC}"
        echo -e "  . .venv/bin/activate"
        echo -e "${YELLOW}Then run this script again.${NC}"
        exit 1
    fi

    # Check pip version: >=26.2.2 is required by the eMudhra/emSign CA incident
    # (and also supports PEP 735 dependency-groups).
    PIP_VERSION=$(python -m pip --version | awk '{print $2}')
    if ! version_ge "$PIP_VERSION" "$MIN_PIP_VERSION"; then
        echo -e "${YELLOW}pip ${PIP_VERSION} trusts the compromised eMudhra/emSign CA certificates; upgrading to >= ${MIN_PIP_VERSION}...${NC}"
        python -m pip install --upgrade "pip>=${MIN_PIP_VERSION}"
    fi

    echo -e "${GREEN}Using pip for installation...${NC}"
    pip install --group dev -e .

    # Install pre-commit hooks
    echo -e "${GREEN}Installing pre-commit hooks...${NC}"
    pre-commit install

    echo -e "${GREEN}Setup complete! You can now run 'make pr' to check your changes, or 'make docs' to build the docs.${NC}"
fi
