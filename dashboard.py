import os
import argparse
from dash import Dash  # Updated import
import dash_bootstrap_components as dbc
from dashboard_app.layout import app_layout
from dashboard_app.callbacks import register_callbacks

app = Dash(__name__, external_stylesheets=[dbc.themes.BOOTSTRAP])

parser = argparse.ArgumentParser(description="TOS Options Dashboard with Polygon API")
parser.add_argument("--docker", help="Change the default server host to 0.0.0.0 for Docker", action='store_true')
args = parser.parse_args()

API_KEY = os.environ.get('POLYGON_API_KEY')
if not API_KEY:
    raise ValueError("POLYGON_API_KEY environment variable is not set. Please provide a valid Polygon API key.")

app.layout = app_layout
register_callbacks(app, API_KEY)

if __name__ == '__main__':
    print(API_KEY)
    host = '0.0.0.0' if args.docker else '127.0.0.1'
    app.run_server(host=host, debug=True, port=8050)
