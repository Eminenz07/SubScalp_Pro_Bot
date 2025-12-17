import json
from connectors.deriv_connector import DerivConnector

# Load config
with open('config/config.json', 'r') as f:
    config = json.load(f)

# Initialize connector
connector = DerivConnector(config)

# Connect
connector.connect()

# Get active symbols
symbols = connector.get_active_symbols()

# Print them
print("Active symbols:")
for sym in symbols:
    print(sym)