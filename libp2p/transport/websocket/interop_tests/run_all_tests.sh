#!/bin/bash

echo "==============================================="
echo "Running py-libp2p WebSocket Interop Tests"
echo "==============================================="

GREEN='\033[0;32m'
RED='\033[0;31m'
NC='\033[0m'

passed=0
failed=0

echo -e "\n[Test 1] JavaScript Client → Python Server"
node tests/test_js_to_py.js > /tmp/test1.log 2>&1
if grep -q '"success": true' /tmp/test1.log; then
    echo -e "${GREEN} PASSED${NC}"
    ((passed++))
else
    echo -e "${RED} FAILED${NC}"
    cat /tmp/test1.log
    ((failed++))
fi

echo -e "\n[Test 2] Python Client → JavaScript Server"
python tests/test_py_to_js.py > /tmp/test2.log 2>&1
if grep -q '"success": true' /tmp/test2.log; then
    echo -e "${GREEN} PASSED${NC}"
    ((passed++))
else
    echo -e "${RED} FAILED${NC}"
    cat /tmp/test2.log
    ((failed++))
fi

echo -e "\n[Test 3] Bidirectional Communication"
python tests/bidirectional_test.py > /tmp/test3.log 2>&1
if grep -q '"success": true' /tmp/test3.log; then
    echo -e "${GREEN} PASSED${NC}"
    ((passed++))
else
    echo -e "${RED} FAILED${NC}"
    cat /tmp/test3.log
    ((failed++))
fi

echo -e "\n==============================================="
echo -e "Test Summary: ${GREEN}${passed} passed${NC}, ${RED}${failed} failed${NC}"
echo -e "==============================================="

exit $failed
