#!/bin/bash

# Exit on any error
set -e

# Define colors for output
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[0;33m'
NC='\033[0m' # No Color

echo -e "${YELLOW}Starting libp2p interoperability tests between Python and Rust implementations${NC}"

# Check if Rust is installed
if ! command -v cargo &> /dev/null; then
    echo -e "${RED}Error: cargo not found. Please install Rust.${NC}"
    exit 1
fi

# Check if python is installed
if ! command -v python3 &> /dev/null; then
    echo -e "${RED}Error: python3 not found. Please install Python 3.${NC}"
    exit 1
fi

# Navigate to the rust-libp2p examples directory
cd .../../../../rust-libp2p/examples

# Make sure the Rust ping example can be built
echo -e "${YELLOW}Building Rust libp2p ping example...${NC}"
cargo build --example ping

# Run the interoperability tests
echo -e "\n${YELLOW}Running Python client to Rust server test...${NC}"
python3 ../libp2p_interop_test.py --mode python-client

echo -e "\n${YELLOW}Running Rust client to Python server test...${NC}"
python3 ../libp2p_interop_test.py --mode rust-client

echo -e "\n${YELLOW}Running bidirectional test...${NC}"
python3 ../libp2p_interop_test.py --mode both

echo -e "\n${GREEN}All interoperability tests completed successfully!${NC}"
