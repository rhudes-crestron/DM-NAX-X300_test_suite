#!/bin/bash
# DM-NAX-X300 Test Suite Runner
# Run automated tests for STM32MP1-based audio devices

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}╔════════════════════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║        DM-NAX-X300 Test Suite (STM32MP1 Platform)         ║${NC}"
echo -e "${BLUE}╚════════════════════════════════════════════════════════════╝${NC}"
echo ""

# Check if virtual environment exists
if [ ! -d "venv" ]; then
    echo -e "${YELLOW}Virtual environment not found. Creating...${NC}"
    python3 -m venv venv
    source venv/bin/activate
    pip install --upgrade pip
    pip install -r requirements.txt
else
    source venv/bin/activate
fi

# Parse command-line arguments
DEVICE=""
MODE="full"
SKIP_PROMPT=false
EXTRA_ARGS=""

while [[ $# -gt 0 ]]; do
    case $1 in
        --device)
            DEVICE="$2"
            shift 2
            ;;
        --quick)
            MODE="quick"
            shift
            ;;
        --skip-prompt)
            SKIP_PROMPT=true
            shift
            ;;
        --help)
            echo "Usage: ./run_tests.sh [OPTIONS]"
            echo ""
            echo "Options:"
            echo "  --device NAME       Run tests on specific device only"
            echo "  --quick             Run quick test subset"
            echo "  --skip-prompt       Skip credential prompt, use config/env only"
            echo "  --help              Show this help message"
            echo ""
            echo "By default, you will be prompted for device credentials."
            echo "To skip the prompt, either:"
            echo "  1. Use --skip-prompt flag and configure devices.yaml"
            echo "  2. Set X300_USERNAME and X300_PASSWORD environment variables"
            echo ""
            echo "Examples:"
            echo "  ./run_tests.sh                           # Run all tests (prompts for credentials)"
            echo "  ./run_tests.sh --quick                   # Quick regression (prompts)"
            echo "  ./run_tests.sh --skip-prompt             # Use config file credentials"
            echo "  X300_USERNAME=admin X300_PASSWORD=pass ./run_tests.sh"
            echo "  ./run_tests.sh --device X300-001         # Test specific device"
            exit 0
            ;;
        *)
            EXTRA_ARGS="$EXTRA_ARGS $1"
            shift
            ;;
    esac
done

# Build pytest command
PYTEST_CMD="pytest -v -s --tb=short"

if [ -n "$DEVICE" ]; then
    PYTEST_CMD="$PYTEST_CMD --device=$DEVICE"
    echo -e "${GREEN}Testing device: $DEVICE${NC}"
fi

if [ "$MODE" == "quick" ]; then
    PYTEST_CMD="$PYTEST_CMD --quick"
    echo -e "${YELLOW}Running in QUICK mode (subset of tests)${NC}"
fi

if [ "$SKIP_PROMPT" = true ]; then
    PYTEST_CMD="$PYTEST_CMD --skip-prompt"
    echo -e "${BLUE}Using credentials from config file or environment${NC}"
fi

# Add HTML report
REPORT_DIR="test_reports"
mkdir -p "$REPORT_DIR"
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
REPORT_FILE="$REPORT_DIR/report_${TIMESTAMP}.html"
PYTEST_CMD="$PYTEST_CMD --html=$REPORT_FILE --self-contained-html"

# Add any extra arguments
if [ -n "$EXTRA_ARGS" ]; then
    PYTEST_CMD="$PYTEST_CMD $EXTRA_ARGS"
fi

echo ""
echo -e "${BLUE}Running tests...${NC}"
echo -e "${BLUE}Command: $PYTEST_CMD${NC}"
echo ""

# Run tests
if $PYTEST_CMD; then
    echo ""
    echo -e "${GREEN}╔════════════════════════════════════════════════════════════╗${NC}"
    echo -e "${GREEN}║                   ALL TESTS PASSED ✓                       ║${NC}"
    echo -e "${GREEN}╚════════════════════════════════════════════════════════════╝${NC}"
    echo -e "${GREEN}Report: $REPORT_FILE${NC}"
    exit 0
else
    EXIT_CODE=$?
    echo ""
    echo -e "${RED}╔════════════════════════════════════════════════════════════╗${NC}"
    echo -e "${RED}║                   TESTS FAILED ✗                           ║${NC}"
    echo -e "${RED}╚════════════════════════════════════════════════════════════╝${NC}"
    echo -e "${RED}Report: $REPORT_FILE${NC}"
    exit $EXIT_CODE
fi
