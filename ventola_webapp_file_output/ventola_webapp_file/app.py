import dash
from dash import html, dcc
from dash.dependencies import Input, Output, State
import datetime
import csv
import os

# === Configurazione ===
MAX_KMH = 10.0
MAX_VOLTAGE = 12.0
LOG_FILE = "logs/controllo_log.csv"

# === Scrittura su file locale per ADECUDAQ ===
def send_to_device(voltage):
    with open("valore_tensione.txt", "w") as f:
        f.write(f"{voltage:.2f}")
    print(f"[File] Salvato valore: {voltage:.2f} V")

# === Log ===
def log_action(kmh, voltage):
    timestamp = datetime.datetime.now().isoformat()
    os.makedirs("logs", exist_ok=True)
    with open(LOG_FILE, mode='a', newline='') as f:
        writer = csv.writer(f, delimiter=';')
        writer.writerow([timestamp, f"{kmh:.2f}", f"{voltage:.2f}"])

# === Calcolo tensione ===
def calculate_voltage(kmh):
    kmh = max(0.0, min(kmh, MAX_KMH))
    voltage = (kmh / MAX_KMH) * MAX_VOLTAGE
    return voltage

# === Dash App ===
app = dash.Dash(__name__)
app.title = "Controllo Ventola ADECUA"

app.layout = html.Div([
    html.H2("Controllo Ventola ADECUA"),
    html.Label("Velocità (km/h):"),
    dcc.Slider(
        id='velocita-slider',
        min=0, max=MAX_KMH, step=0.1,
        marks={i: f"{i}" for i in range(0, int(MAX_KMH)+1)},
        value=0
    ),
    html.Div(id='output-kmh', style={'marginTop': '20px'}),
    html.Div(id='output-volt'),
    html.Button("Stop Ventola", id='stop-button', n_clicks=0, style={'marginTop': '20px'}),
    html.Hr(),
    html.H4("Grafico delle tensioni inviate"),
    dcc.Graph(id='grafico-log'),
    dcc.Interval(id="interval-update", interval=5000, n_intervals=0),
])

@app.callback(
    Output('output-kmh', 'children'),
    Output('output-volt', 'children'),
    Input('velocita-slider', 'value'),
    Input('stop-button', 'n_clicks'),
    prevent_initial_call=True
)
def update_output(kmh_value, stop_clicks):
    ctx = dash.callback_context
    if ctx.triggered and ctx.triggered[0]['prop_id'] == 'stop-button.n_clicks':
        send_to_device(0.0)
        log_action(0.0, 0.0)
        return "🛑 Ventola fermata", "🔌 Tensione inviata: 0.00 V"
    else:
        voltage = calculate_voltage(kmh_value)
        send_to_device(voltage)
        log_action(kmh_value, voltage)
        return f"✅ Velocità impostata: {kmh_value:.2f} km/h", f"🔌 Tensione inviata: {voltage:.2f} V"

@app.callback(
    Output("grafico-log", "figure"),
    Input("interval-update", "n_intervals")
)
def update_graph(n):
    import plotly.graph_objs as go
    timestamps, kmhs, volts = [], [], []
    if os.path.exists(LOG_FILE):
        with open(LOG_FILE, newline='') as f:
            reader = csv.reader(f, delimiter=';')
            for row in reader:
                timestamps.append(row[0])
                kmhs.append(float(row[1]))
                volts.append(float(row[2]))
    return {
        "data": [
            go.Scatter(x=timestamps, y=kmhs, name="Velocità (km/h)", mode='lines+markers'),
            go.Scatter(x=timestamps, y=volts, name="Tensione (V)", mode='lines+markers')
        ],
        "layout": go.Layout(
            title="Storico comandi inviati",
            xaxis_title="Timestamp",
            yaxis_title="Valore",
            height=400
        )
    }

if __name__ == '__main__':
    app.run(host='127.0.0.1', port=8050, debug=True)
