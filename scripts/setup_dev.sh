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

# Check if uv is available
if command -v uv &> /dev/null; then
    echo -e "${GREEN}Using uv for installation (recommended)...${NC}"
    # Check if virtual environment flag is set
    if [[ -z "$VIRTUAL_ENV" ]]; then
        echo -e "${YELLOW}No virtual environment detected. Creating one with uv...${NC}"
        uv venv
        echo -e "${YELLOW}Activate it with:${NC}"
        echo -e "  source .venv/bin/activate"
        echo -e "${YELLOW}Then run this script again.${NC}"
        exit 1
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

    echo -e "${GREEN}Setup complete! You can now run 'make pr' to check your changes.${NC}"
else
    # Check if virtual environment flag is set
    if [[ -z "$VIRTUAL_ENV" ]]; then
        echo -e "${YELLOW}Warning: Not in a virtual environment. Creating one...${NC}"
        python3 -m venv .venv
        echo -e "${GREEN}Virtual environment created. Activate it with:${NC}"
        echo -e "  source .venv/bin/activate"
        echo -e "${YELLOW}Then run this script again.${NC}"
        exit 1
    fi

    # Check pip version
    PIP_VERSION=$(pip --version | grep -oE '[0-9]+\.[0-9]+' | head -1)
    PIP_MAJOR=$(echo $PIP_VERSION | cut -d. -f1)
    PIP_MINOR=$(echo $PIP_VERSION | cut -d. -f2)

    # PEP 735 dependency-groups support requires pip >= 25.1
    if [ "$PIP_MAJOR" -lt 25 ] || ([ "$PIP_MAJOR" -eq 25 ] && [ "$PIP_MINOR" -lt 1 ]); then
        echo -e "${YELLOW}Upgrading pip to support PEP 735 dependency-groups...${NC}"
        pip install --upgrade pip
    fi

    echo -e "${GREEN}Using pip for installation...${NC}"
    pip install --group dev -e .

    # Install pre-commit hooks
    echo -e "${GREEN}Installing pre-commit hooks...${NC}"
    pre-commit install

    echo -e "${GREEN}Setup complete! You can now run 'make pr' to check your changes.${NC}"
fi
