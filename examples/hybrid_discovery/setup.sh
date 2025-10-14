#!/bin/bash

set -e

echo "🚀 Setting up Hybrid Discovery System Demo"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Function to print colored output
print_status() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

print_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Check if Python is installed
if ! command -v python3 &> /dev/null; then
    print_error "Python 3 is required but not installed"
    exit 1
fi

# Check if Node.js is installed
if ! command -v node &> /dev/null; then
    print_error "Node.js is required but not installed"
    exit 1
fi

# Check if npm is installed
if ! command -v npm &> /dev/null; then
    print_error "npm is required but not installed"
    exit 1
fi

print_status "Installing Python dependencies..."
pip3 install base58 trio

print_status "Installing optional Ethereum dependencies..."
pip3 install web3 eth-account || print_warning "Ethereum dependencies not installed - will use mock registry"

print_success "Setup completed successfully!"

echo ""
echo "🎯 Next Steps:"
echo "1. Run the server demo (with mock Ethereum):"
echo "   python3 demo.py --mode server"
echo ""
echo "2. Run the client demo:"
echo "   python3 demo.py --mode client --bootstrap <SERVER_ADDRESS>"
echo ""
echo "3. For real Ethereum integration:"
echo "   - Install web3 and eth-account: pip install web3 eth-account"
echo "   - Start local Ethereum node"
echo "   - Deploy smart contract"
echo "   - Use --ethereum-rpc, --contract-address, --private-key flags"
echo ""
echo "📖 For detailed instructions, see README.md"
