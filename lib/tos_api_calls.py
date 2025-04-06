from polygon.rest import RESTClient
import datetime

# Initialize Polygon client (assumes API key is passed or set in environment)
def get_polygon_client(apiKey=None):
    if apiKey is None:
        raise ValueError("Polygon API Key is not defined.")
    return RESTClient(api_key=apiKey)

# Polygon API call to get historical price data (OHLCV) for a ticker
def tos_get_price_hist(ticker_symbol: str, period=1, periodType='year', frequencyType='daily', frequency=1, startDate=None, endDate=None, apiKey=None):
    client = get_polygon_client(apiKey)
    timespan_map = {
        'day': 'day' if frequencyType == 'daily' else 'minute',
        'month': 'month',
        'year': 'year',
        'ytd': 'day'
    }
    timespan = timespan_map.get(periodType.lower(), 'day')
    multiplier = frequency
    from_date = startDate or (datetime.datetime.now() - datetime.timedelta(days=365)).strftime('%Y-%m-%d')
    to_date = endDate or datetime.datetime.now().strftime('%Y-%m-%d')

    try:
        aggs = client.get_aggs(
            ticker=ticker_symbol,
            multiplier=multiplier,
            timespan=timespan,
            from_=from_date,
            to=to_date,
            limit=50000
        )
        if not aggs:
            print(f"No aggregates returned for {ticker_symbol} from {from_date} to {to_date}")
            return {"candles": []}
        
        candles = [
            {
                "open": a.open,
                "high": a.high,
                "low": a.low,
                "close": a.close,
                "volume": a.volume,
                "datetime": a.timestamp
            } for a in aggs
        ]
        print(f"Fetched {len(candles)} candles for {ticker_symbol} from {from_date} to {to_date}")
        return {"candles": candles}
    except Exception as e:
        print(f"Error fetching data for {ticker_symbol}: {str(e)}")
        return {"candles": []}

# Polygon API call to get real-time quote data for a ticker
def tos_get_quotes(ticker_symbols: str, apiKey=None):
    client = get_polygon_client(apiKey)
    quote = client.get_last_quote(ticker_symbols)
    trade = client.get_last_trade(ticker_symbols)
    
    # Format to match TOS structure (single ticker for simplicity)
    return {
        ticker_symbols: {
            "lastPrice": trade.price,
            "bidPrice": quote.bid_price,
            "askPrice": quote.ask_price
        }
    }

# Polygon API call to search tickers
def tos_search(symbol: str, projection='desc-search', apiKey=None):
    client = get_polygon_client(apiKey)
    tickers = client.list_tickers(search=symbol, limit=100)
    
    # Format to match TOS structure
    return {
        str(i): {
            "symbol": ticker.ticker,
            "description": ticker.name
        } for i, ticker in enumerate(tickers)
    }

# Polygon API call to get historical close prices as a list
def tos_load_price_hist(ticker_symbol: str, period=1, startDate=None, endDate=None, apiKey=None) -> list:
    data = tos_get_price_hist(ticker_symbol, period=period, startDate=startDate, endDate=endDate, apiKey=apiKey)
    return [candle['close'] for candle in data['candles']]

# Polygon API call to get option chain data
def tos_get_option_chain(ticker_symbol: str, contractType='ALL', rangeType='OTM', apiKey=None):
    client = get_polygon_client(apiKey)
    options = []
    print(f"Fetching options chain for {ticker_symbol}")
    
    params = {}
    if contractType != 'ALL':
        params["contract_type"] = contractType.lower()
    
    for opt in client.list_snapshot_options_chain(ticker_symbol, params=params):
        delta = opt.greeks.delta if opt.greeks and opt.greeks.delta is not None else 'NaN'
        options.append({
            "putCall": opt.details.contract_type.upper(),
            "strikePrice": opt.details.strike_price,
            "expirationDate": int(datetime.datetime.strptime(opt.details.expiration_date, '%Y-%m-%d').timestamp() * 1000),
            "bid": opt.last_quote.bid or 0,
            "ask": opt.last_quote.ask or 0,
            "lastPrice": opt.last_trade.price if opt.last_trade else 0,
            "openInterest": opt.open_interest,
            "volume": opt.day.volume,
            "delta": delta,
            "multiplier": 100
        })
    print(f"Fetched {len(options)} options for {ticker_symbol}")
    
    trade = client.get_last_trade(ticker_symbol)
    underlying_price = trade.price if trade else 0
    print(f"Underlying price for {ticker_symbol}: {underlying_price}")
    
    call_exp_date_map = {}
    put_exp_date_map = {}
    for opt in options:
        exp_date = f"{datetime.datetime.fromtimestamp(opt['expirationDate'] / 1000).strftime('%Y-%m-%d')}:{int((opt['expirationDate'] / 1000 - datetime.datetime.now().timestamp()) / 86400)}"
        strike_key = str(opt['strikePrice'])
        if opt['putCall'] == 'CALL':
            call_exp_date_map.setdefault(exp_date, {})[strike_key] = [opt]
        else:
            put_exp_date_map.setdefault(exp_date, {})[strike_key] = [opt]
    
    return {
        "underlyingPrice": underlying_price,
        "callExpDateMap": call_exp_date_map,
        "putExpDateMap": put_exp_date_map
    }

# Polygon API call to get fundamental data (limited compared to TOS)
def tos_get_fundamental_data(ticker_symbol: str, apiKey=None, search='fundamental', raw=False):
    client = get_polygon_client(apiKey)
    details = client.get_ticker_details(ticker_symbol)
    
    # Format to match TOS structure (simplified)
    data = {
        ticker_symbol: {
            "fundamental": {
                "symbol": details.ticker,
                "description": details.name,
                "marketCap": details.market_cap,
                "sharesOutstanding": details.share_class_shares_outstanding
            }
        }
    }
    return data if not raw else data  # Raw flag preserved but less relevant here
