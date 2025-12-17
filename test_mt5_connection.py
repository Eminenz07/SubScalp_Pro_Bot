import MetaTrader5 as mt5
import os
from dotenv import load_dotenv
load_dotenv()

# Load credentials from env
login = int(os.getenv('MT5_LOGIN')) if os.getenv('MT5_LOGIN') else None
password = os.getenv('MT5_PASSWORD')
server = os.getenv('MT5_SERVER')

print(f"Attempting MT5 initialization...")
if mt5.initialize():
    print("MT5 initialized successfully.")
    if login and password and server:
        if mt5.login(login, password=password, server=server):
            print("MT5 login successful.")
            account_info = mt5.account_info()
            print(f"Account equity: {account_info.equity}")
        else:
            print("MT5 login failed.")
    else:
        print("No credentials provided.")
    
    # Test data fetching
    symbol = 'EURUSD'
    timeframe = mt5.TIMEFRAME_M5
    rates = mt5.copy_rates_from_pos(symbol, timeframe, 0, 10)
    if rates is not None and len(rates) > 0:
        print("Successfully fetched recent data.")
    else:
        print("Failed to fetch recent data.")
    
    # Test historical
    from datetime import datetime
    start = datetime(2024, 1, 1)
    end = datetime(2024, 1, 2)
    rates_hist = mt5.copy_rates_range(symbol, timeframe, start, end)
    if rates_hist is not None and len(rates_hist) > 0:
        print("Successfully fetched historical data.")
    else:
        print("Failed to fetch historical data.")
    
    mt5.shutdown()
else:
    print("MT5 initialization failed.")