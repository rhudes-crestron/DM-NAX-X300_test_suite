"""
DM-NAX-X300 Test Suite - Pytest Configuration
"""
import os
import sys
import pytest
import yaml
import getpass
from pathlib import Path

# Add lib directory to Python path
sys.path.insert(0, str(Path(__file__).parent / "lib"))


def pytest_addoption(parser):
    """Add custom command-line options."""
    parser.addoption(
        "--device",
        action="store",
        default=None,
        help="Specific device name to test (from devices.yaml)"
    )
    parser.addoption(
        "--quick",
        action="store_true",
        default=False,
        help="Run quick test subset only"
    )
    parser.addoption(
        "--skip-firmware-check",
        action="store_true",
        default=False,
        help="Skip firmware version verification"
    )
    parser.addoption(
        "--skip-prompt",
        action="store_true",
        default=False,
        help="Skip interactive credential prompt, use config/env only"
    )


def pytest_configure(config):
    """Configure pytest markers."""
    config.addinivalue_line(
        "markers", "quick: marks tests as quick (subset for faster regression)"
    )
    config.addinivalue_line(
        "markers", "slow: marks tests as slow (full validation)"
    )
    config.addinivalue_line(
        "markers", "x300: marks tests specific to X300 platform"
    )
    config.addinivalue_line(
        "markers", "stm32mp1: marks tests for STM32MP1-based devices"
    )
    config.addinivalue_line(
        "markers", "audio: marks audio-related tests"
    )
    config.addinivalue_line(
        "markers", "network: marks network-related tests"
    )
    config.addinivalue_line(
        "markers", "firmware: marks firmware upgrade tests"
    )


@pytest.fixture(scope="session")
def config_data(request):
    """Load device configuration from YAML."""
    config_path = Path(__file__).parent / "config" / "devices.yaml"
    with open(config_path, 'r') as f:
        config = yaml.safe_load(f)
    
    # Check if credentials/IP are already provided via environment
    ip_address = os.getenv('X300_IP')
    username = os.getenv('X300_USERNAME')
    password = os.getenv('X300_PASSWORD')
    
    # Check if user wants to skip the prompt
    skip_prompt = request.config.getoption("--skip-prompt")
    
    # If not provided and not skipping, prompt the user
    if not (ip_address and username and password) and not skip_prompt:
        print("\n" + "="*60)
        print("X300 Device Configuration Required")
        print("="*60)
        
        if not ip_address:
            default_ip = list(config.get('devices', {}).values())[0].get('ip', '192.168.1.246')
            ip_address = input(f"Enter device IP [{default_ip}]: ").strip()
            if not ip_address:
                ip_address = default_ip
        
        if not username:
            username = input("Enter username [admin]: ").strip()
            if not username:
                username = "admin"
        
        if not password:
            password_prompt = "Enter password [admin123]: "
            password = getpass.getpass(password_prompt)
            if not password:
                password = "admin123"
                print("Using default password: admin123")
        
        print("="*60 + "\n")
    
    # Override config with provided values
    for device_name, device_config in config.get('devices', {}).items():
        if ip_address:
            device_config['ip'] = ip_address
        if username:
            device_config['username'] = username
        if password:
            device_config['password'] = password
    
    return config


@pytest.fixture(scope="session")
def test_settings(config_data):
    """Return test execution settings."""
    return config_data.get('test_settings', {})


@pytest.fixture(scope="session")
def device_list(config_data, request):
    """Return list of devices to test."""
    devices = config_data.get('devices', {})
    
    # Filter by --device option if specified
    device_name = request.config.getoption("--device")
    if device_name:
        if device_name not in devices:
            pytest.exit(f"Device '{device_name}' not found in config")
        return {device_name: devices[device_name]}
    
    return devices


@pytest.fixture(scope="function")
def device_config(device_list, request):
    """
    Parametrized fixture providing device configuration.
    Use with @pytest.mark.parametrize or directly in tests.
    """
    # Get first device from list for non-parametrized tests
    device_name = list(device_list.keys())[0]
    return device_name, device_list[device_name]


def pytest_collection_modifyitems(config, items):
    """Modify test collection based on options."""
    if config.getoption("--quick"):
        # Skip slow tests in quick mode
        skip_slow = pytest.mark.skip(reason="Skipped in quick mode")
        for item in items:
            if "slow" in item.keywords:
                item.add_marker(skip_slow)


def pytest_report_header(config):
    """Add custom header to pytest output."""
    return [
        "DM-NAX-X300 Test Suite",
        "Platform: STM32MP1-based devices",
        f"Config: {Path(__file__).parent / 'config' / 'devices.yaml'}"
    ]


@pytest.fixture(scope="function", autouse=True)
def test_logger(request):
    """Automatic logging for each test."""
    test_name = request.node.name
    print(f"\n{'='*60}")
    print(f"Starting test: {test_name}")
    print(f"{'='*60}")
    
    yield
    
    print(f"\n{'='*60}")
    print(f"Completed test: {test_name}")
    print(f"{'='*60}\n")
