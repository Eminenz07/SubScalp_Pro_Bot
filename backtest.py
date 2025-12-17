import json
import argparse
from datetime import datetime, timedelta
import pandas as pd
import MetaTrader5 as mt5
import matplotlib.pyplot as plt
from tqdm import tqdm
import numpy as np
import random
from core.strategy_ema_stochastic import StrategyEMAStochastic
from core.strategy_lsmc import StrategyLSMC
from core.strategy_rsi_fibonacci import StrategyRSIFibonacci

# Load config
with open('config/config.json', 'r') as f:
    config = json.load(f)

# MT5 connection
def connect_mt5():
    mt5_cfg = config.get('mt5', {})
    if not mt5.initialize():
        print("Failed to initialize MT5")
        return False
    # Login if credentials available
    login = mt5_cfg.get('login')
    password = mt5_cfg.get('password')
    server = mt5_cfg.get('server')
    if login and password and server:
        if not mt5.login(int(login), password=password, server=server):
            print("MT5 login failed")
            mt5.shutdown()
            return False
    return True

def shutdown_mt5():
    mt5.shutdown()

# Placeholder for strategies
def ema_strategy(df, params):
    # Simple EMA crossover strategy
    fast_period = params['ema']['fast_period']
    slow_period = params['ema']['slow_period']
    atr_period = params['atr']['period']
    atr_mult = params['atr']['multiplier']
    rr = params.get('risk_reward', 2.0)
    
    # Compute indicators
    df['ema_fast'] = df['close'].ewm(span=fast_period, adjust=False).mean()
    df['ema_slow'] = df['close'].ewm(span=slow_period, adjust=False).mean()
    df['atr'] = pd.concat([abs(df['high'] - df['low']), 
                           abs(df['high'] - df['close'].shift()), 
                           abs(df['low'] - df['close'].shift())], axis=1).max(axis=1).ewm(span=atr_period, adjust=False).mean()
    
    # Signals
    df['signal'] = 0
    buy = (df['ema_fast'] > df['ema_slow']) & (df['ema_fast'].shift() <= df['ema_slow'].shift())
    sell = (df['ema_fast'] < df['ema_slow']) & (df['ema_fast'].shift() >= df['ema_slow'].shift())
    df.loc[buy, 'signal'] = 1
    df.loc[sell, 'signal'] = -1
    
    df['sl_distance'] = atr_mult * df['atr']
    df['tp_distance'] = rr * df['sl_distance']
    return df

def ema_stochastic_strategy(df, params):
    # EMA + Stochastic + RSI hybrid
    fast_period = params['ema']['fast_period']
    slow_period = params['ema']['slow_period']
    atr_period = params['atr']['period']
    atr_mult = params['atr']['multiplier']
    rsi_period = params['rsi']['period']
    k_period = params['stochastic']['k_period']
    d_period = params['stochastic']['d_period']
    smooth = params['stochastic']['smooth']
    rr = params.get('risk_reward', 2.0)
    
    # EMA
    df['ema_fast'] = df['close'].ewm(span=fast_period, adjust=False).mean()
    df['ema_slow'] = df['close'].ewm(span=slow_period, adjust=False).mean()
    
    # ATR
    df['atr'] = pd.concat([abs(df['high'] - df['low']), 
                           abs(df['high'] - df['close'].shift()), 
                           abs(df['low'] - df['close'].shift())], axis=1).max(axis=1).ewm(span=atr_period, adjust=False).mean()
    
    # RSI
    delta = df['close'].diff()
    gain = (delta.where(delta > 0, 0)).ewm(span=rsi_period, adjust=False).mean()
    loss = (-delta.where(delta < 0, 0)).ewm(span=rsi_period, adjust=False).mean()
    rs = gain / loss
    df['rsi'] = 100 - (100 / (1 + rs))
    
    # Stochastic
    low_min = df['low'].rolling(window=k_period).min()
    high_max = df['high'].rolling(window=k_period).max()
    df['stoch_k'] = 100 * (df['close'] - low_min) / (high_max - low_min)
    df['stoch_k'] = df['stoch_k'].rolling(window=smooth).mean()
    df['stoch_d'] = df['stoch_k'].rolling(window=d_period).mean()
    
    # Signals
    bull_cross = (df['stoch_k'].shift(1) < df['stoch_d'].shift(1)) & (df['stoch_k'] > df['stoch_d'])
    bear_cross = (df['stoch_k'].shift(1) > df['stoch_d'].shift(1)) & (df['stoch_k'] < df['stoch_d'])
    
    buy = (df['ema_fast'] > df['ema_slow']) & (df['rsi'] > 50) & bull_cross
    sell = (df['ema_fast'] < df['ema_slow']) & (df['rsi'] < 50) & bear_cross
    
    df['signal'] = 0
    df.loc[buy, 'signal'] = 1
    df.loc[sell, 'signal'] = -1
    
    df['sl_distance'] = atr_mult * df['atr']
    df['tp_distance'] = rr * df['sl_distance']
    return df

# Main backtest function
# Load strategies params
with open('config/strategies.json', 'r') as f:
    strategy_params = json.load(f)

def fetch_data(symbol, timeframe, start, end):
    timeframe_map = {
        'M5': mt5.TIMEFRAME_M5,
        'M15': mt5.TIMEFRAME_M15,
        'M30': mt5.TIMEFRAME_M30,
        # Add more timeframes as needed
    }
    tf = timeframe_map.get(timeframe, mt5.TIMEFRAME_M5)
    
    start_time = int(start.timestamp())
    end_time = int(end.timestamp())
    
    rates = mt5.copy_rates_range(symbol, tf, start_time, end_time)
    if rates is None or len(rates) == 0:
        print(f"No data for {symbol}")
        return pd.DataFrame()
    
    df = pd.DataFrame(rates)
    df['timestamp'] = pd.to_datetime(df['time'], unit='s')
    df = df[['timestamp', 'open', 'high', 'low', 'close', 'tick_volume']]
    df.rename(columns={'tick_volume': 'volume'}, inplace=True)
    df.set_index('timestamp', inplace=True)
    return df

def get_symbol_specs(symbol):
    info = mt5.symbol_info(symbol)
    if info is None:
        return {'point': 0.00001, 'tick_value': 1.0}  # Defaults
    return {
        'point': info.point,
        'tick_value': info.trade_tick_value
    }

def ema_stochastic_mt_strategy(df_m5, params, symbol, start, end):
    # Wrapper for multi-timeframe EMA Stochastic
    strategy = StrategyEMAStochastic('config/ema_stochastic_config.json')
    
    # Fetch M30 data for trend
    df_m30 = fetch_data(symbol, 'M30', start, end)
    if df_m30.empty:
        print(f"No M30 data for {symbol}, skipping multi-timeframe analysis.")
        return df_m5  # No signals if no trend data
    
    trend = strategy.check_trend(df_m30)
    df_signals = strategy.generate_signals(df_m5, trend)
    return df_signals

def simulate_dual_engine(df_m5, df_m15, symbol, initial_equity, risk_per_trade, config, monte_carlo_runs=0, random_seed=None):
    lsmc = StrategyLSMC(config)
    rsi_fib = StrategyRSIFibonacci(config)
    trades = []
    equity = initial_equity
    equity_curve = [initial_equity]
    open_position = None

    specs = get_symbol_specs(symbol)
    point = specs['point']
    tick_value = specs['tick_value']

    # Realistic backtest parameters
    slippage_pct = 0.1  # 0.1 ATR slippage
    spread_cost = 0.0001  # 1 pip spread (adjust per symbol)
    execution_delay = 1  # 1 bar delay simulation

    for idx in df_m5.index:
        # Slice up to current time
        df5_slice = df_m5.loc[:idx]
        df15_slice = df_m15.loc[:idx]

        price = float(df5_slice['close'].iloc[-1])

        # Check current open position for SL/TP hit on this bar
        if open_position is not None:
            entry_price = open_position['entry_price']
            sl = open_position['sl']
            tp = open_position['tp']
            size = open_position['size']
            side = open_position['side']

            high = float(df5_slice['high'].iloc[-1])
            low = float(df5_slice['low'].iloc[-1])

            hit_sl = False
            hit_tp = False
            exit_price = None
            result = 'loss'

            if side == 'buy':
                if low <= sl:
                    hit_sl = True
                    exit_price = sl
                elif high >= tp:
                    hit_tp = True
                    exit_price = tp
                    result = 'win'
            else:
                if high >= sl:
                    hit_sl = True
                    exit_price = sl
                elif low <= tp:
                    hit_tp = True
                    exit_price = tp
                    result = 'win'

            if hit_sl or hit_tp:
                profit = (exit_price - entry_price) * size if side == 'buy' else (entry_price - exit_price) * size
                trades.append({
                    'Pair': symbol,
                    'Strategy': 'DUAL_ENGINE',
                    'Engine': open_position.get('engine', 'A'),
                    'Entry Time': open_position['entry_time'],
                    'Exit Time': idx,
                    'Entry Price': entry_price,
                    'Exit Price': exit_price,
                    'Result': result,
                    'Profit': profit,
                    'SL': sl,
                    'TP': tp
                })
                equity += profit
                equity_curve.append(equity)
                open_position = None

        # If no open position, evaluate for a new signal via Engine A gate
        if open_position is None and not df15_slice.empty:
            decision, ctx = lsmc.evaluate_market(df5_slice, df15_slice)
            signal_row = None
            engine_used = None
            if decision == 'ALLOW_ENGINE_A_TRADE':
                sig_df_a = lsmc.generate_signals(df5_slice, df15_slice)
                if sig_df_a is not None and not sig_df_a.empty:
                    signal_row = sig_df_a.iloc[-1].to_dict()
                    engine_used = 'A'
            elif decision == 'ALLOW_ENGINE_B_EVALUATION':
                sig_df_b = rsi_fib.generate_signals(df5_slice, df15_slice)
                if sig_df_b is not None and not sig_df_b.empty:
                    signal_row = sig_df_b.iloc[-1].to_dict()
                    engine_used = 'B'

            if signal_row:
                sig = int(signal_row.get('signal', 0) or 0)
                if sig != 0:
                    sl_distance = float(signal_row.get('sl_distance', 0.0) or 0.0)
                    tp_distance = float(signal_row.get('tp_distance', 0.0) or 0.0)
                    # Size calculation consistent with existing backtest
                    risk_amount = equity * risk_per_trade
                    points_in_sl = sl_distance / point if point and point > 0 else float('nan')
                    loss_if_sl_hit = tick_value * points_in_sl if tick_value and points_in_sl == points_in_sl else float('nan')
                    size = risk_amount / loss_if_sl_hit if (loss_if_sl_hit and loss_if_sl_hit > 0) else float('nan')
                    if not np.isfinite(size) or size <= 0:
                        size = 0.01
                    if size > 0:
                        # Realistic execution: apply slippage and spread
                        atr_val = float(df5_slice['atr_14'].iloc[-1] or 0.0) if 'atr_14' in df5_slice.columns else 0.0
                        slippage = random.uniform(-slippage_pct, slippage_pct) * atr_val
                        spread_cost_points = spread_cost / point if point and point > 0 else 0.0

                        if sig > 0:
                            entry_price = price + slippage + spread_cost_points
                            sl = entry_price - sl_distance
                            tp = entry_price + tp_distance
                            side = 'buy'
                        else:
                            entry_price = price + slippage - spread_cost_points
                            sl = entry_price + sl_distance
                            tp = entry_price - tp_distance
                            side = 'sell'
                        open_position = {
                            'entry_time': idx,
                            'entry_price': entry_price,
                            'sl': sl,
                            'tp': tp,
                            'size': size,
                            'side': side,
                            'engine': engine_used or 'A'
                        }

    # Close any remaining position at end
    if open_position:
        profit = 0
        trades.append({
            'Pair': symbol,
            'Strategy': 'DUAL_ENGINE',
            'Engine': open_position.get('engine', 'A'),
            'Entry Time': open_position['entry_time'],
            'Exit Time': df_m5.index[-1],
            'Entry Price': open_position['entry_price'],
            'Exit Price': df_m5['close'].iloc[-1],
            'Result': 'closed',
            'Profit': profit,
            'SL': open_position['sl'],
            'TP': open_position['tp']
        })
        equity += profit
        equity_curve.append(equity)

    # Monte Carlo reshuffling if requested
    if monte_carlo_runs > 0:
        random.seed(random_seed)
        mc_trades = []
        mc_equity_curves = []
        for _ in range(monte_carlo_runs):
            shuffled_trades = trades.copy()
            random.shuffle(shuffled_trades)
            mc_equity = initial_equity
            mc_equity_curve = [mc_equity]
            for t in shuffled_trades:
                mc_equity += t['Profit']
                mc_equity_curve.append(mc_equity)
            mc_trades.append(shuffled_trades)
            mc_equity_curves.append(mc_equity_curve)
        return pd.DataFrame(trades), equity_curve, mc_trades, mc_equity_curves

    return pd.DataFrame(trades), equity_curve, [], []

def simulate_trades(df, strategy, params, symbol, initial_equity, risk_per_trade, start=None, end=None):
    if strategy == ema_stochastic_mt_strategy:
        df = strategy(df, params, symbol, start, end)
    else:
        df = strategy(df.copy(), params)
    trades = []
    equity = initial_equity
    equity_curve = [initial_equity]
    open_position = None
    current_pnl = 0

    # Debug: report signals count per symbol
    signals_count = int((df['signal'] != 0).sum()) if 'signal' in df.columns else 0
    if signals_count == 0:
        print(f"No signals generated for {symbol} in the selected period.")

    for idx, row in df.iterrows():
        price = row['close']
        
        # Check if open position hit SL/TP
        if open_position:
            entry_price = open_position['entry_price']
            sl = open_position['sl']
            tp = open_position['tp']
            size = open_position['size']
            side = open_position['side']
            
            high = row['high']
            low = row['low']
            
            hit_sl = False
            hit_tp = False
            exit_price = None
            result = 'loss'
            
            if side == 'buy':
                if low <= sl:
                    hit_sl = True
                    exit_price = sl
                elif high >= tp:
                    hit_tp = True
                    exit_price = tp
                    result = 'win'
            else:  # sell
                if high >= sl:
                    hit_sl = True
                    exit_price = sl
                elif low <= tp:
                    hit_tp = True
                    exit_price = tp
                    result = 'win'
            
            if hit_sl or hit_tp:
                if side == 'buy':
                    profit = (exit_price - entry_price) * size
                else:
                    profit = (entry_price - exit_price) * size
                
                trades.append({
                    'Pair': symbol,
                    'Strategy': strategy.__name__,
                    'Entry Time': open_position['entry_time'],
                    'Exit Time': idx,
                    'Entry Price': entry_price,
                    'Exit Price': exit_price,
                    'Result': result,
                    'Profit': profit,
                    'SL': sl,
                    'TP': tp
                })
                
                equity += profit
                equity_curve.append(equity)
                open_position = None
        
        # Open new position if signal and no open
        if open_position is None and row['signal'] != 0:
            side = 'buy' if row['signal'] > 0 else 'sell'
            sl_distance = row['sl_distance']
            tp_distance = row['tp_distance']
            
            specs = get_symbol_specs(symbol)
            point = specs['point']
            tick_value = specs['tick_value']
            
            risk_amount = equity * risk_per_trade
            points_in_sl = sl_distance / point if point and point > 0 else float('nan')
            loss_if_sl_hit = tick_value * points_in_sl if tick_value and points_in_sl == points_in_sl else float('nan')
            size = risk_amount / loss_if_sl_hit if (loss_if_sl_hit and loss_if_sl_hit > 0) else float('nan')

            # Fallback if size is invalid (nan/inf/<=0)
            if not np.isfinite(size) or size <= 0:
                size = 0.01
            
            if size > 0:
                if side == 'buy':
                    sl = price - sl_distance
                    tp = price + tp_distance
                else:
                    sl = price + sl_distance
                    tp = price - tp_distance
                
                open_position = {
                    'entry_time': idx,
                    'entry_price': price,
                    'sl': sl,
                    'tp': tp,
                    'size': size,
                    'side': side
                }
    
    # Close any remaining position at end
    if open_position:
        profit = 0  # Or calculate based on last price
        trades.append({
                    'Pair': symbol,
                    'Strategy': strategy.__name__,
                    'Entry Time': open_position['entry_time'],
                    'Exit Time': df.index[-1],
                    'Entry Price': open_position['entry_price'],
                    'Exit Price': df['close'].iloc[-1],
                    'Result': 'closed',
                    'Profit': profit,
                    'SL': open_position['sl'],
                    'TP': open_position['tp']
                })
        equity += profit
        equity_curve.append(equity)
    
    return pd.DataFrame(trades), equity_curve

def calculate_metrics(trades, equity_curve, start_date, end_date):
    if trades.empty:
        return {}
    
    total_trades = len(trades)
    wins = len(trades[trades['Result'] == 'win'])
    losses = len(trades[trades['Result'] == 'loss'])
    win_rate = (wins / total_trades * 100) if total_trades > 0 else 0
    net_pnl = trades['Profit'].sum()
    gross_profit = trades[trades['Profit'] > 0]['Profit'].sum()
    gross_loss = abs(trades[trades['Profit'] < 0]['Profit'].sum())
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else float('inf')
    
    peak = max(equity_curve)
    drawdowns = [peak - e for e in equity_curve]
    max_dd = max(drawdowns) / peak * 100 if peak > 0 else 0
    
    avg_rr = trades[trades['Result'] == 'win']['Profit'].mean() / abs(trades[trades['Result'] == 'loss']['Profit'].mean()) if losses > 0 else 0
    
    return {
        'Total Trades': total_trades,
        'Wins': wins,
        'Losses': losses,
        'Win Rate': win_rate,
        'Net PnL': net_pnl,
        'Profit Factor': profit_factor,
        'Max Drawdown': max_dd,
        'Avg RR': avg_rr,
        'Period': f"{start_date.date()} to {end_date.date()}"
    }

def run_backtest(strategy, pairs, start_date, end_date):
    if not connect_mt5():
        return None, None
    
    all_data = {}
    for pair in tqdm(pairs):
        df = fetch_data(pair, config['timeframe'], start_date, end_date)
        if not df.empty:
            all_data[pair] = df
    
    initial_equity = config.get('equity', 10000)
    risk_per_trade = config['risk_per_trade']
    
    all_trades = pd.DataFrame()
    overall_equity_curve = [initial_equity]
    overall_metrics = {}
    
    print("\n------------------------------")
    print(f"SubScalp WealthBot Backtest")
    print(f"Strategy: {strategy.__name__.replace('_strategy', '')}")
    print(f"Pairs: {', '.join(pairs)}")
    print("------------------------------")
    
    for pair, df in all_data.items():
        if strategy == 'DUAL_ENGINE':
            df_m5 = df
            df_m15 = fetch_data(pair, 'M15', start_date, end_date)
            if df_m15.empty:
                print(f"No M15 data for {pair}, skipping.")
                continue
            trades, equity_curve = simulate_dual_engine(df_m5, df_m15, pair, overall_equity_curve[-1], risk_per_trade, config)
        else:
            trades, equity_curve = simulate_trades(df, strategy, strategy_params, pair, overall_equity_curve[-1], risk_per_trade, start_date, end_date)
        all_trades = pd.concat([all_trades, trades])

        metrics = calculate_metrics(trades, equity_curve, start_date, end_date)
        overall_metrics[pair] = metrics
        
        print(f"Pair: {pair}")
        if not metrics:
            print("No trades generated for this pair.")
        else:
            print(f"Total Trades: {metrics['Total Trades']}")
            print(f"Wins: {metrics['Wins']} | Losses: {metrics['Losses']}")
            print(f"Win Rate: {metrics['Win Rate']:.2f}%")
            print(f"Net PnL: +${metrics['Net PnL']:.2f}")
            print(f"Profit Factor: {metrics['Profit Factor']:.2f}")
            print(f"Avg RR: {metrics['Avg RR']:.2f}")
            print(f"Max Drawdown: {metrics['Max Drawdown']:.1f}%")
            if strategy == 'DUAL_ENGINE' and 'Engine' in trades.columns:
                try:
                    eng_a = trades[trades['Engine'] == 'A']
                    eng_b = trades[trades['Engine'] == 'B']
                    a_total = len(eng_a)
                    b_total = len(eng_b)
                    a_wins = len(eng_a[eng_a['Result'] == 'win'])
                    b_wins = len(eng_b[eng_b['Result'] == 'win'])
                    a_wr = (a_wins / a_total * 100) if a_total > 0 else 0.0
                    b_wr = (b_wins / b_total * 100) if b_total > 0 else 0.0
                    a_pnl = eng_a['Profit'].sum() if a_total > 0 else 0.0
                    b_pnl = eng_b['Profit'].sum() if b_total > 0 else 0.0
                    print(f"Engine A: Trades {a_total}, WinRate {a_wr:.2f}%, NetPnL ${a_pnl:.2f}")
                    print(f"Engine B: Trades {b_total}, WinRate {b_wr:.2f}%, NetPnL ${b_pnl:.2f}")
                except Exception:
                    pass
        print("------------------------------")
        
        overall_equity_curve.extend(equity_curve[1:])  # Append without duplicating last
    
    # Overall metrics
    overall_trades = len(all_trades)
    if overall_trades > 0:
        overall_net_pnl = all_trades['Profit'].sum()
        print(f"Overall Net PnL: +${overall_net_pnl:.2f}")
    
    # Save to CSV
    csv_name = f"backtest_results_{strategy.__name__.replace('_strategy', '')}.csv"
    all_trades.to_csv(csv_name, index=False)
    print(f"Trade history saved to {csv_name}")
    
    shutdown_mt5()
    
    return all_trades, overall_equity_curve

def plot_results(equity_curve, trades):
    plt.figure(figsize=(12, 6))
    plt.subplot(2, 1, 1)
    plt.plot(equity_curve, label='Equity Curve')
    plt.title('Backtest Equity Curve')
    plt.legend()
    
    # Drawdown
    peak = np.maximum.accumulate(equity_curve)
    drawdown = (peak - equity_curve) / peak * 100
    plt.subplot(2, 1, 2)
    plt.fill_between(range(len(drawdown)), drawdown, 0, alpha=0.3)
    plt.title('Drawdown %')
    
    plt.tight_layout()
    plt.show()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="SubScalp WealthBot Backtest")
    parser.add_argument('--strategy', type=str, choices=['EMA', 'EMA_STOCHASTIC', 'DUAL_ENGINE'], help='Strategy to backtest')
    parser.add_argument('--start', type=str, help='Start date (YYYY-MM-DD)')
    parser.add_argument('--end', type=str, help='End date (YYYY-MM-DD)')
    parser.add_argument('--visualize', action='store_true', help='Visualize results')
    
    args = parser.parse_args()
    
    # Prompt if not provided
    if not args.strategy:
        strategy_name = input("Select strategy (EMA or EMA_STOCHASTIC): ").strip().upper()
    else:
        strategy_name = args.strategy.upper()
    
    if strategy_name == 'EMA':
        strategy_func = ema_strategy
    elif strategy_name == 'EMA_STOCHASTIC':
        strategy_func = ema_stochastic_strategy
    elif strategy_name == 'DUAL_ENGINE':
        strategy_func = 'DUAL_ENGINE'
    else:
        print("Invalid strategy")
        exit(1)
    
    today = datetime.now()
    default_end = today
    default_start = today - timedelta(days=180)  # 6 months
    
    if not args.start:
        start_str = input(f"Enter start date (YYYY-MM-DD) or press Enter for default ({default_start.date()}): ") or str(default_start.date())
    else:
        start_str = args.start
    
    if not args.end:
        end_str = input(f"Enter end date (YYYY-MM-DD) or press Enter for default ({default_end.date()}): ") or str(default_end.date())
    else:
        end_str = args.end
    
    start_date = datetime.strptime(start_str, '%Y-%m-%d')
    end_date = datetime.strptime(end_str, '%Y-%m-%d')
    
    broker = config['broker']
    pairs = config[broker]['symbols'] if broker in config and 'symbols' in config[broker] else config.get('symbols', [])
    
    all_trades, overall_equity_curve = run_backtest(strategy_func, pairs, start_date, end_date)
    
    if args.visualize:
        print("Visualization enabled. Plotting results...")
        plot_results(overall_equity_curve, all_trades)