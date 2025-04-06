import os
import argparse
import dash  # Recommend updating to a newer version, e.g., >=2.0.0
import dash_bootstrap_components as dbc

# Source guide: Callbacks layout separation (https://community.plotly.com/t/dash-callback-in-a-separate-file/14122/16)
from dashboard_app.layout import app_layout
from dashboard_app.callbacks import register_callbacks

# Initialize Dash app with Bootstrap theme
app = dash.Dash(__name__, external_stylesheets=[dbc.themes.BOOTSTRAP])

# Docker support
parser = argparse.ArgumentParser(description="TOS Options Dashboard with Polygon API")
parser.add_argument("--docker", help="Change the default server host to 0.0.0.0 for Docker", action='store_true')
args = parser.parse_args()

# API credentials
API_KEY = os.environ.get('POLYGON_API_KEY')
if not API_KEY:
    raise ValueError("POLYGON_API_KEY environment variable is not set. Please provide a valid Polygon API key.")

# App layout
app.layout = app_layout

# Connect Plotly graphs with Dash components
register_callbacks(app, API_KEY)

if __name__ == '__main__':
    host = '0.0.0.0' if args.docker else '127.0.0.1'
    app.run_server(host=host, debug=True, port=8050)
