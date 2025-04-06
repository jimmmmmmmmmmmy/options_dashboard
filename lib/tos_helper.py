def extract_price_field(hist_price, field='close'):
    """
    Extract a list of specified field values from historical price data.
    
    Args:
        hist_price (dict): Historical price data with a 'candles' key.
        field (str): Field to extract (e.g., 'close', 'open', 'high', 'low', 'volume'). Defaults to 'close'.
    
    Returns:
        list: List of values for the specified field.
    
    Raises:
        KeyError: If 'candles' or the specified field is missing.
    """
    if not isinstance(hist_price, dict) or 'candles' not in hist_price:
        raise KeyError("Input must be a dictionary with a 'candles' key")
    
    output_ls = []
    for candle in hist_price['candles']:
        if field not in candle:
            raise KeyError(f"Each candle must have a '{field}' key")
        output_ls.append(candle[field])
    
    return output_ls

# Alias for backward compatibility
create_pricelist = extract_price_field
