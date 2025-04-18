import collections
import pandas as pd
import statistics as stat
from datetime import datetime, timedelta, date

import plotly.graph_objects as go

from dash.dependencies import Input, Output, State
from dash.exceptions import PreventUpdate
from dashboard_app.layout import base_df_columns, ticker_df_columns, option_chain_df_columns
from lib.tos_api_calls import tos_search, tos_get_quotes, tos_get_option_chain, tos_get_price_hist
from lib.gbm import gbm_sim
from lib.stats import get_hist_volatility, prob_cone, get_prob

def register_callbacks(app, API_KEY):
    @app.callback(
        Output("ticker_table_collapse_content", "is_open"),
        [Input("ticker_data", "n_clicks")],
        [State("ticker_table_collapse_content", "is_open")],
    )
    def toggle_collapse(n, is_open):
        return not is_open if n else is_open

    @app.callback(
        Output('memory-ticker', 'options'),
        [Input('memory-ticker', 'search_value'), Input('ticker_switch__input', 'value')],
        [State('memory-ticker', 'value')]
    )
    def update_search(search_value, ticker_switch, value):
        if not search_value:
            raise PreventUpdate
        json_data = tos_search(search_value, projection='symbol-search' if ticker_switch else 'desc-search', apiKey=API_KEY)
        try:
            options = [{"label": f"{dict_item['description']} (Symbol: {dict_item['symbol']})", "value": dict_item['symbol']} for dict_item in json_data.values()]
            if value:
                options.extend({"label": sel, "value": sel} for sel in value)
            return options
        except:
            return []

    @app.callback(
        Output('storage-historical', 'data'),
        [Input('submit-button-state', 'n_clicks')],
        [State('memory-ticker', 'value'), State('memory-vol-period', 'value'), State('memory-volest-type', 'value')]
    )
    def get_historical_prices(n_clicks, ticker, volatility_period, vol_est_type):
        if not ticker or not isinstance(ticker, str):
            print(f"Invalid ticker: {ticker}")
            raise PreventUpdate
        print(f"Fetching history for ticker: {ticker}, period: {volatility_period}, estimator: {vol_est_type}")
        hist_data = tos_get_price_hist(ticker, apiKey=API_KEY)
        json_data = {ticker: hist_data}
        price_df = pd.DataFrame(hist_data['candles'])
        if price_df.empty or 'close' not in price_df.columns:
            print(f"No valid historical data for {ticker}")
            json_data['est_vol'] = 0
        else:
            vol_series = get_hist_volatility(price_df, volatility_period, estimator=vol_est_type)
            json_data['est_vol'] = vol_series.iloc[-1] if not vol_series.empty else 0
        print(f"Returning hist_data with {len(hist_data['candles'])} candles, est_vol: {json_data.get('est_vol')}")
        return json_data

    @app.callback(
        Output('storage-quotes', 'data'),
        [Input('submit-button-state', 'n_clicks')],
        [State('memory-ticker', 'value')]
    )
    def get_price_quotes(n_clicks, ticker):
        if ticker is None:
            raise PreventUpdate
        return tos_get_quotes(ticker, apiKey=API_KEY)

    @app.callback(
        Output('storage-option-chain-all', 'data'),
        [Input('submit-button-state', 'n_clicks'), Input('storage-historical', 'data'), Input('storage-quotes', 'data')],
        [State('memory-ticker', 'value'), State('memory-expdays', 'value'), State('memory-confidence', 'value')]
    )
    def get_option_chain_all(n_clicks, hist_data, quotes_data, ticker, expday_range, confidence_lvl):
        if not ticker or not hist_data or not hist_data.get(ticker):
            print(f"Skipping get_option_chain_all: ticker={ticker}, hist_data={hist_data}")
            raise PreventUpdate
        print(f"Fetching options chain for {ticker}, expday_range={expday_range}")
        json_data = tos_get_option_chain(ticker, contractType='ALL', rangeType='ALL', apiKey=API_KEY)
        print(f"Options chain data: {json_data}")
        
        insert = []
        current_date = datetime.now()
        price_df = pd.DataFrame(hist_data[ticker]['candles'])
        hist_volatility = hist_data.get('est_vol', 0)
        stock_price = quotes_data[ticker]['lastPrice']

        for option_chain_type in ['call', 'put']:
            exp_map = json_data[f'{option_chain_type}ExpDateMap']
            for exp_date, strikes in exp_map.items():
                for strike in strikes.values():
                    strike_data = strike[0]
                    expiry_date = datetime.fromtimestamp(strike_data["expirationDate"] / 1000.0)
                    day_diff = (expiry_date - current_date).days
                    if day_diff < 0:
                        continue
                    if day_diff > expday_range:
                        break

                    option_type = strike_data['putCall']
                    strike_price = strike_data['strikePrice']
                    bid_size = strike_data.get('bidSize', 0)
                    ask_size = strike_data.get('askSize', 0)
                    delta_val = strike_data['delta']
                    total_volume = strike_data['volume']
                    open_interest = strike_data['openInterest']
                    option_premium = round(strike_data['bid'] * strike_data['multiplier'], 2)
                    roi_val = round(option_premium / (strike_price * 100) * 100, 2)

                    # Handle 'NaN' or None delta_val
                    if delta_val == 'NaN' or delta_val is None:
                        option_leverage = 0.0
                    else:
                        option_leverage = 0.0 if option_premium == 0 else round((abs(float(delta_val)) * stock_price) / option_premium, 3)
                    
                    prob_val = get_prob(stock_price, strike_price, hist_volatility, day_diff) if day_diff > 0 else 0.0
                    lower_bound, upper_bound = prob_cone(stock_price, hist_volatility, day_diff, confidence_lvl)

                    insert.append([ticker, expiry_date, option_type, strike_price, day_diff, delta_val, prob_val, open_interest, total_volume, option_premium, option_leverage, bid_size, ask_size, roi_val, lower_bound, upper_bound])

        df = pd.DataFrame(insert, columns=[col['name'] for col in base_df_columns])
        return df.to_json(orient='split')

    @app.callback(
        Output('price_chart', 'figure'),
        [Input('storage-historical', 'data'), Input('tabs_price_chart', 'value')],
        [State('memory-ticker', 'value')]
    )
    def on_data_set_price_history(hist_data, tab, ticker):
        aggregation = collections.defaultdict(lambda: collections.defaultdict(list))
        if ticker is None:
            raise PreventUpdate

        if tab == 'price_tab_1':  # 1 Day
            hist_price = tos_get_price_hist(ticker, periodType='day', period=1, frequencyType='minute', frequency=1, apiKey=API_KEY)
        elif tab == 'price_tab_2':  # 5 Days
            hist_price = tos_get_price_hist(ticker, periodType='day', period=5, frequencyType='minute', frequency=5, apiKey=API_KEY)
        elif tab == 'price_tab_3':  # 1 Month
            hist_price = tos_get_price_hist(ticker, periodType='month', period=1, frequencyType='daily', frequency=1, apiKey=API_KEY)
        elif tab == 'price_tab_4':  # 1 Year
            hist_price = hist_data[ticker]
            if hist_price is None:
                raise PreventUpdate
        elif tab == 'price_tab_5':  # 5 Years
            hist_price = tos_get_price_hist(ticker, periodType='year', period=5, frequencyType='daily', frequency=1, startDate=datetime.now() - timedelta(days=5*365), apiKey=API_KEY)

        for candle in hist_price['candles']:
            a = aggregation[ticker]
            a['name'] = ticker
            a['mode'] = 'lines'
            a['y'].append(candle['close'])
            a['x'].append(datetime.fromtimestamp(candle['datetime'] / 1000.0))

        return {'layout': {'title': {'text': 'Price History'}}, 'data': [x for x in aggregation.values()]}

    @app.callback(
        Output('prob_cone_chart', 'figure'),
        [Input('storage-option-chain-all', 'data'), Input('storage-historical', 'data'), Input('storage-quotes', 'data'), Input('tabs_prob_chart', 'value')],
        [State('memory-ticker', 'value'), State('memory-expdays', 'value'), State('memory-confidence', 'value')]
    )
    def on_data_set_prob_cone(optionchain_data, hist_data, quotes_data, tab, ticker, expday_range, confidence_lvl):
        if not optionchain_data or not hist_data or not quotes_data:
            print(f"Skipping on_data_set_prob_cone: optionchain_data={optionchain_data}, hist_data={hist_data}, quotes_data={quotes_data}")
            raise PreventUpdate

        insert = []
        data = []
        optionchain_df = pd.read_json(StringIO(optionchain_data), orient='split')  # Fix FutureWarning
        mkt_pressure_df = optionchain_df.filter(['Ticker', 'Exp. Date (Local)', 'Option Type', 'Exp. Days', 'Strike', 'Open Int.', 'Total Vol.'])
        mkt_pressure_df['Day'] = mkt_pressure_df['Exp. Days'].apply(lambda x: date.today() + timedelta(days=x))
        mkt_pressure_df['StrikeOpenInterest'] = mkt_pressure_df['Strike'] * mkt_pressure_df['Open Int.']
        mkt_pressure_df['StrikeTotalVolume'] = mkt_pressure_df['Strike'] * mkt_pressure_df['Total Vol.']

        price_df = pd.DataFrame(hist_data[ticker]['candles'])
        hist_volatility = hist_data.get('est_vol', 0)
        stock_price = quotes_data[ticker]['lastPrice']

        if tab == 'prob_cone_tab':
            for i_day in range(expday_range + 1):
                lower_bound, upper_bound = prob_cone(stock_price, hist_volatility, i_day, probability=confidence_lvl)
                insert.append([ticker, date.today() + timedelta(days=i_day), stock_price, lower_bound, upper_bound, i_day])

            agg_mkt_pressure_df = mkt_pressure_df.groupby('Day').sum().reset_index()
            agg_mkt_pressure_df['MktPressOpenInterest'] = agg_mkt_pressure_df['StrikeOpenInterest'] / agg_mkt_pressure_df['Open Int.']
            agg_mkt_pressure_df['MktPressTotalVolume'] = agg_mkt_pressure_df['StrikeTotalVolume'] / agg_mkt_pressure_df['Total Vol.']

        elif tab == 'gbm_sim_tab':
            T = expday_range / 252
            r, q, sigma, steps, N = 0.01, 0.007, hist_volatility, 1, 1000000
            x_ls, y_ls = gbm_sim(price_df, stock_price, T, r, q, sigma, steps, N, bin_size=10)
            data.append(go.Scatter(x=x_ls, y=y_ls, name='Price Probability', mode='lines+markers', line_shape='spline'))

        if tab == 'prob_cone_tab':
            df = pd.DataFrame(insert, columns=['Ticker Symbol', 'Day', 'Stock Price', 'Lower Bound', 'Upper Bound', 'Days to Expiry'])
            fig = go.Figure()
            fig.add_trace(go.Scatter(x=df.loc[df['Ticker Symbol'] == ticker, 'Day'].squeeze(), y=df.loc[df['Ticker Symbol'] == ticker, 'Upper Bound'].squeeze(), mode='lines+markers', name=f'{ticker}: Upper Bound', line_shape='spline'))
            fig.add_trace(go.Scatter(x=df.loc[df['Ticker Symbol'] == ticker, 'Day'].squeeze(), y=df.loc[df['Ticker Symbol'] == ticker, 'Lower Bound'].squeeze(), mode='lines+markers', name=f'{ticker}: Lower Bound', line_shape='spline'))
            fig.add_trace(go.Scatter(x=agg_mkt_pressure_df['Day'].squeeze(), y=agg_mkt_pressure_df['MktPressOpenInterest'].squeeze(), mode='lines+markers', name=f'{ticker}: Open Interest Pressure', line_shape='spline'))
            fig.add_trace(go.Scatter(x=agg_mkt_pressure_df['Day'].squeeze(), y=agg_mkt_pressure_df['MktPressTotalVolume'].squeeze(), mode='lines+markers', name=f'{ticker}: Total Volume Pressure', line_shape='spline'))
            fig.update_layout(title=f'Probability Cone ({confidence_lvl*100}% Confidence)', title_x=0.5, yaxis_title='Stock Price', plot_bgcolor='rgb(256,256,256)')
            fig.update_layout(legend=dict(yanchor="top", y=1, xanchor="left", x=0))
        else:
            fig = go.Figure(data=data)
            fig.update_layout(title='Probability Distribution', title_x=0.5, yaxis_title='Probability (%)', plot_bgcolor='rgb(256,256,256)')

        fig.update_xaxes(showgrid=True, gridcolor='LightGrey')
        fig.update_yaxes(showgrid=True, gridcolor='LightGrey')
        return fig

    @app.callback(
        Output('vol_chart', 'figure'),
        [Input('storage-historical', 'data'), Input('tabs_vol_chart', 'value')],
        [State('memory-ticker', 'value')]
    )
    def on_data_set_vol_history(hist_data, tab, ticker):
        if hist_data is None:
            raise PreventUpdate
        price_df = pd.DataFrame(hist_data[ticker]['candles'])
        vol_tab_dict = {'vol_tab_2w': 14, 'vol_tab_1M': 30, 'vol_tab_3M': 90, 'vol_tab_1Y': 252}
        volatility_period = vol_tab_dict[tab]
        vol_est_ls = ['log_returns', 'garman_klass', 'hodges_tompkins', 'parkinson', 'rogers_satchell', 'yang_zhang']
        hist_volatility_dict = {}

        for vol_est in vol_est_ls:
            hist_volatility = get_hist_volatility(price_df, volatility_period, estimator=vol_est)
            hist_volatility_dict[vol_est] = hist_volatility.iloc[1:] if vol_est in ('garman_klass', 'parkinson', 'rogers_satchell') else hist_volatility

        hist_volatility_dict['Day'] = range(1, len(hist_volatility_dict['log_returns']) + 1)
        hist_volatility_df = pd.DataFrame(hist_volatility_dict)
        fig = go.Figure()
        for vol_est in vol_est_ls:
            fig.add_trace(go.Scatter(x=hist_volatility_df['Day'].squeeze(), y=hist_volatility_df[vol_est].squeeze(), mode='lines+markers', name=f'{ticker}: {vol_est}', line_shape='spline'))
        fig.update_layout(title=f'Historical Volatility (Window: {volatility_period} days)', title_x=0.5, xaxis_title='Days', yaxis_title='Estimated Volatility', plot_bgcolor='rgb(256,256,256)')
        fig.update_xaxes(showgrid=True, gridcolor='LightGrey')
        fig.update_yaxes(showgrid=True, gridcolor='LightGrey')
        return fig

    @app.callback(
        [Output('open_ir_vol', 'figure'), Output('memory_exp_day_graph', 'options')],
        [Input('storage-option-chain-all', 'data')],
        [State('memory-ticker', 'value'), State('memory-expdays', 'value'), State('memory_exp_day_graph', 'value')]
    )
    def on_data_init_open_interest_vol(optionchain_data, ticker, expday_range, expday_graph_selection):
        if optionchain_data is None:
            raise PreventUpdate
        optionchain_df = pd.read_json(optionchain_data, orient='split')
        df = optionchain_df.filter(['Ticker', 'Exp. Date (Local)', 'Type', 'Exp. Days', 'Strike', 'Open Int.', 'Total Vol.'])
        expday_options = [{"label": f"Strike Date: {(datetime.now() + timedelta(days=int(days_to_exp))).date()} (Days to Expiry: {days_to_exp})", "value": days_to_exp} for days_to_exp in df['Exp. Days'].unique()]
        fig = go.Figure()
        expday_select = expday_graph_selection if expday_graph_selection else df['Exp. Days'].max()

        for option_type, bar_color in [('PUT', 'indianred'), ('CALL', 'lightseagreen')]:
            fig.add_trace(go.Scatter(x=df.loc[(df['Type'] == option_type) & (df['Exp. Days'] == expday_select), 'Strike'].squeeze(), y=df.loc[(df['Type'] == option_type) & (df['Exp. Days'] == expday_select), 'Total Vol.'].squeeze(), mode='lines+markers', name=f'{ticker}: Total {option_type} Volume', line_shape='spline', marker_color=bar_color))
            fig.add_trace(go.Bar(x=df.loc[(df['Type'] == option_type) & (df['Exp. Days'] == expday_select), 'Strike'].squeeze(), y=df.loc[(df['Type'] == option_type) & (df['Exp. Days'] == expday_select), 'Open Int.'].squeeze(), name=f'{ticker}: Open {option_type} Interest', marker_color=bar_color, opacity=0.5))

        fig.update_layout(title=f'Open Interest/Volume - {expday_select} days', title_x=0.5, xaxis_title='Strike Price', yaxis_title='No. of Contracts', plot_bgcolor='rgb(256,256,256)', legend=dict(yanchor="top", y=1, xanchor="right", x=1))
        return fig, expday_options

    @app.callback(
        Output('ticker-data-table', 'data'),
        [Input('submit-button-state', 'n_clicks'), Input('storage-historical', 'data'), Input('storage-option-chain-all', 'data'), Input('ticker-data-table', "page_current"), Input('ticker-data-table', "page_size"), Input('ticker-data-table', "sort_by")],
        [State('memory-ticker', 'value')]
    )
    def on_data_set_ticker_table(n_clicks, hist_data, optionchain_data, page_current, page_size, sort_by, ticker):
        if ticker is None or optionchain_data is None:
            raise PreventUpdate
        option_chain_response = tos_get_option_chain(ticker, contractType='ALL', rangeType='ALL', apiKey=API_KEY)
        if not option_chain_response or 'error' in option_chain_response:
            raise PreventUpdate

        stock_price = option_chain_response['underlyingPrice']
        stock_price_110percent = stock_price * 1.1
        stock_price_90percent = stock_price * 0.9
        insert = []

        low_call_strike, high_call_strike, low_put_strike, high_put_strike = None, None, None, None
        for option_chain_type in ['call', 'put']:
            for exp_date, strikes in option_chain_response[f'{option_chain_type}ExpDateMap'].items():
                day_diff = int(exp_date.split(':')[1])
                if not (28 <= day_diff < 35):
                    continue
                high_strike_found = False
                for strike in strikes.values():
                    strike_price = strike[0]['strikePrice']
                    if option_chain_type == 'call':
                        if strike_price < stock_price_90percent:
                            low_call_strike, low_call_strike_bid, low_call_strike_ask = strike_price, strike[0]['bid'], strike[0]['ask']
                        elif strike_price > stock_price_110percent and not high_strike_found:
                            high_call_strike, high_call_strike_bid, high_call_strike_ask = strike_price, strike[0]['bid'], strike[0]['ask']
                            high_strike_found = True
                    elif option_chain_type == 'put':
                        if strike_price < stock_price_90percent:
                            low_put_strike, low_put_strike_bid, low_put_strike_ask = strike_price, strike[0]['bid'], strike[0]['ask']
                        elif strike_price > stock_price_110percent and not high_strike_found:
                            high_put_strike, high_put_strike_bid, high_put_strike_ask = strike_price, strike[0]['bid'], strike[0]['ask']
                            high_strike_found = True

        strike_checklist = [low_call_strike, high_call_strike, low_put_strike, high_put_strike]
        if all(item is None for item in strike_checklist):
            raise PreventUpdate

        prevent_zero_div = lambda x, y: 0 if (y == 0 or y is None) else x / y
        high_call_strike_askbid = prevent_zero_div(high_call_strike_ask, high_call_strike_bid)
        high_put_strike_askbid = prevent_zero_div(high_put_strike_ask, high_put_strike_bid)
        low_call_strike_askbid = prevent_zero_div(low_call_strike_ask, low_call_strike_bid)
        low_put_strike_askbid = prevent_zero_div(low_put_strike_ask, low_put_strike_bid)
        askbid_checklist = [high_call_strike_askbid, high_put_strike_askbid, low_call_strike_askbid, low_put_strike_askbid]
        liquidity = 'FAILED' if all(askbid > 1.25 for askbid in askbid_checklist) else 'PASSED'

        high_call_strike_midpoint = (high_call_strike_bid + high_call_strike_ask) / 2
        high_put_strike_midpoint = (high_put_strike_bid + high_put_strike_ask) / 2
        low_call_strike_midpoint = (low_call_strike_bid + low_call_strike_ask) / 2
        low_put_strike_midpoint = (low_put_strike_bid + low_put_strike_ask) / 2
        call_110percent_price = low_call_strike_midpoint - (low_call_strike_midpoint - high_call_strike_midpoint) / (high_call_strike - low_call_strike) * (stock_price_110percent - low_call_strike)
        put_90percent_price = low_put_strike_midpoint + (high_put_strike_midpoint - low_put_strike_midpoint) / (high_put_strike - low_put_strike) * (stock_price_90percent - low_put_strike)

        skew_category = 'Put Skew' if put_90percent_price > call_110percent_price else 'Call Skew'
        skew = round(put_90percent_price / call_110percent_price, 3) if put_90percent_price > call_110percent_price else round(call_110percent_price / put_90percent_price, 3)
        insert.append([ticker, skew_category, skew, liquidity])

        df = pd.DataFrame(insert, columns=[col['id'] for col in ticker_df_columns])
        dff = df.sort_values([col['column_id'] for col in sort_by], ascending=[col['direction'] == 'asc' for col in sort_by], inplace=False) if sort_by else df
        return dff.iloc[page_current * page_size:(page_current + 1) * page_size].to_dict('records')

    @app.callback(
        Output('option-chain-table', 'data'),
        [Input('submit-button-state', 'n_clicks'), Input('storage-option-chain-all', 'data'), Input('storage-historical', 'data'), Input('option-chain-table', "page_current"), Input('option-chain-table', "page_size"), Input('option-chain-table', "sort_by")],
        [State('memory-roi', 'value'), State('memory-delta', 'value')]
    )
    def on_data_set_table(n_clicks, optionchain_data, hist_data, page_current, page_size, sort_by, roi_selection, delta_range):
        if hist_data is None or optionchain_data is None:
            raise PreventUpdate
        base_df = pd.read_json(optionchain_data, convert_dates=['Exp. Date (Local)'], orient='split')
        df = base_df.loc[(base_df['ROI'] >= roi_selection) & (base_df['Delta'].abs() <= delta_range)]
        df = df.loc[((df['Type'] == 'CALL') & (df['Strike'] >= df['Upper CI'])) | ((df['Type'] == 'PUT') & (df['Strike'] <= df['Lower CI']))]
        df = df.drop(columns=['Upper CI', 'Lower CI'])
        df['ROI'] = df['ROI'].map('{:.3f}'.format)
        df['Leverage'] = df['Leverage'].map('{:.3f}'.format)
        df['Delta'] = df['Delta'].map('{:.3f}'.format)
        df.columns = [col['id'] for col in option_chain_df_columns]
        dff = df.sort_values([col['column_id'] for col in sort_by], ascending=[col['direction'] == 'asc' for col in sort_by], inplace=False) if sort_by else df
        return dff.iloc[page_current * page_size:(page_current + 1) * page_size].to_dict('records')
