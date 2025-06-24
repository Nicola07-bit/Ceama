import dash
from dash import html, dcc
from dash.dependencies import Input, Output, State
import datetime
import csv
import os
import sys
import time
import threading
import pysoem

# --- INIZIO SEZIONE ETHERCAT SPECIFICA ---
# Parametri del dispositivo Beckhoff EtherCAT (Confermati dai file ESI e dall'immagine EL4001)
BECKHOFF_VENDOR_ID = 0x00000002
BECKHOFF_AO_PRODUCT_CODE = 0x017f017  # EL4001 Product Code
AO1_OUTPUT_OFFSET = 0
AO1_OUTPUT_SIZE = 2  # 16 bits = 2 bytes

# Variabili globali per lo stato della comunicazione EtherCAT
ethercat_lock = threading.Lock()  # Per proteggere le variabili globali in un ambiente multi-thread/callback
master = None
adecua_slave = None
ethercat_status_message = "EtherCAT: Inattivo (Attesa inizializzazione)."  # Messaggio di stato per l'UI


def initialize_ethercat_device_logic():
    """
    Logica di inizializzazione EtherCAT.
    Tenta di trovare e inizializzare il master EtherCAT sulla prima interfaccia valida
    che riesce a connettersi e trovare lo slave Beckhoff EL4001.
    """
    global master, adecua_slave

    print(
        f"\n[EtherCAT Init Logic] Tentativo di inizializzazione... Master attuale: {master is not None}, Slave attuale: {adecua_slave is not None}")

    # Se un master esiste già, prova a chiuderlo per pulizia prima di ricrearlo
    if master:
        try:
            print("[EtherCAT Init Logic] Chiusura del Master esistente per nuova inizializzazione.")
            master.close()
        except Exception as e:
            print(f"[EtherCAT Init Logic] Errore durante la chiusura del Master esistente: {e}")
        master = None  # Resetta per sicurezza
        adecua_slave = None
        time.sleep(0.1)  # Breve pausa

    # AGGIUNGI QUESTO BLOCCO: Attesa iniziale solo se non abbiamo ancora un master
    if master is None:
        print("[EtherCAT Init Logic] Nessun master attivo. Attesa di 3 secondi prima del primo tentativo di apertura.")
        time.sleep(3)  # Aumenta il tempo di attesa a 3 secondi

    # Ottieni tutte le interfacce disponibili
    interfaces = []
    try:
        interfaces = pysoem.master.interfaces
        if not interfaces:
            print(
                "[EtherCAT Init Logic] Nessuna interfaccia di rete trovata da pysoem. Assicurati che Npcap sia installato e il driver sia attivo.")
            return False
    except Exception as e:
        print(f"[EtherCAT Init Error] Errore durante il recupero delle interfacce di rete: {e}")
        return False

    # Prova ogni interfaccia finché non ne troviamo una che funziona
    for iface_name in interfaces:
        print(f"\n[EtherCAT Init Logic] Tentativo di inizializzazione sull'interfaccia: {iface_name}")
        current_master = None
        current_adecua_slave = None
        try:
            current_master = pysoem.Master(iface_name)
            print(f"[EtherCAT Init Logic] Master creato sull'interfaccia {iface_name}. Tentativo di config_init()...")
            current_master.config_init()
            current_master.config_dc()

            found_adecua = False
            for slave in current_master.slaves:
                if (slave.desc['vendor_id'] == BECKHOFF_VENDOR_ID and
                        slave.desc['product_code'] == BECKHOFF_AO_PRODUCT_CODE):
                    current_adecua_slave = slave
                    found_adecua = True
                    break

            if not found_adecua:
                print(
                    f"[EtherCAT Init Logic] Nessun modulo Beckhoff EL4001 trovato sull'interfaccia {iface_name}. Provando la prossima.")
                current_master.close()  # Chiudi il master per liberare l'interfaccia
                continue  # Prova la prossima interfaccia

            print(
                f"[EtherCAT Init Logic] Modulo EL4001 trovato sull'interfaccia {iface_name}. Tentativo di config_map()...")
            current_master.config_map()

            # Porta gli slave nello stato SAFEOP
            print("[EtherCAT Init Logic] Tentativo di portare in SAFEOP_STATE...")
            current_master.state_check(pysoem.SAFEOP_STATE, timeout=2000)
            current_master.read_state()
            if current_adecua_slave.state != pysoem.SAFEOP_STATE:
                raise Exception(
                    f"Slave Beckhoff EL4001 non in SAFEOP_STATE. Stato attuale: {current_adecua_slave.state_check()}.")
            print("[EtherCAT Init Logic] EL4001 in SAFEOP_STATE. Tentativo di portare in OPERATIONAL_STATE...")

            # Porta gli slave nello stato OPERATIONAL
            current_adecua_slave.state = pysoem.OPERATIONAL_STATE
            current_master.state_check(pysoem.OPERATIONAL_STATE, timeout=2000)
            current_master.read_state()
            if current_adecua_slave.state != pysoem.OPERATIONAL_STATE:
                raise Exception(
                    f"Impossibile portare Beckhoff EL4001 in OPERATIONAL_STATE. Stato attuale: {current_adecua_slave.state_check()}.")

            print(
                f"[EtherCAT Init Logic] Dispositivo Beckhoff EL4001 inizializzato e in OPERATIONAL_STATE sull'interfaccia: {iface_name}.")

            # Assegna alle variabili globali SOLO se tutto ha avuto successo
            master = current_master
            adecua_slave = current_adecua_slave
            return True  # Indica successo e termina

        except pysoem.SOEMError as e:
            print(f"[EtherCAT Init Error] Errore SOEM sull'interfaccia {iface_name}: {e}")
            if current_master:
                try:
                    current_master.close()
                except:
                    pass
            current_master = None
            current_adecua_slave = None
            # Continua a provare la prossima interfaccia in caso di errore SOEM

        except Exception as e:
            print(f"[EtherCAT Init Error] Errore generico sull'interfaccia {iface_name}: {e}")
            if current_master:
                try:
                    current_master.close()
                except:
                    pass
            current_master = None
            current_adecua_slave = None
            # Continua a provare la prossima interfaccia in caso di errore generico

    print("[EtherCAT Init Error] Nessuna interfaccia EtherCAT funzionante trovata con lo slave Beckhoff EL4001.")
    master = None
    adecua_slave = None
    return False  # Indica fallimento dopo aver provato tutte le interfacce


def send_to_device(voltage):
    """Invia il valore di tensione all'uscita AO.1 del modulo EL4001 tramite EtherCAT."""
    global master, adecua_slave, ethercat_status_message

    with ethercat_lock:  # Usa il lock per proteggere l'accesso alle variabili globali
        print(f"[EtherCAT Send] Inizio invio. Master: {master is not None}, Slave: {adecua_slave is not None}")
        if not master or not adecua_slave:
            ethercat_status_message = "EtherCAT: Master/Slave non inizializzato. Tentativo riconnessione..."
            print("[EtherCAT Send Warning] Master o Slave non inizializzato. Ritorno False.")
            return False

        # Verifica lo stato operativo esplicitamente
        master_operational = master.is_state(pysoem.OPERATIONAL_STATE)
        slave_operational = adecua_slave.state == pysoem.OPERATIONAL_STATE
        if not master_operational or not slave_operational:
            ethercat_status_message = f"EtherCAT: Master: {'OK' if master_operational else 'NOK'}, Slave: {'OK' if slave_operational else 'NOK'}. Riprovo."
            print(
                f"[EtherCAT Send Warning] Master o Slave non in OPERATIONAL (Master OK:{master_operational}, Slave OK:{slave_operational}). Ritorno False.")
            return False

        try:
            voltage = max(0.0, min(voltage, MAX_VOLTAGE))
            raw_value = int((voltage / MAX_VOLTAGE) * 32767)
            raw_value = max(0, min(raw_value, 32767))
            raw_value_bytes = raw_value.to_bytes(AO1_OUTPUT_SIZE, byteorder='little', signed=True)

            adecua_slave.output[AO1_OUTPUT_OFFSET: AO1_OUTPUT_OFFSET + AO1_OUTPUT_SIZE] = raw_value_bytes

            master.send_processdata()
            master.receive_processdata(timeout=1000)

            print(f"[EtherCAT Send] Tensione {voltage:.2f} V inviata a AO.1 (Raw: {raw_value}).")
            ethercat_status_message = f"EtherCAT: OK. Ultima tensione: {voltage:.2f} V."
            return True

        except pysoem.SOEMError as e:
            ethercat_status_message = f"EtherCAT: Errore SOEM I/O! {e}"
            print(f"[EtherCAT Send Error] Errore SOEM durante l'invio della tensione: {e}")
            # In caso di errore SOEM, chiudi e forza la riconnessione
            try:
                if master: master.close()
            except:
                pass
            master = None
            adecua_slave = None
            return False
        except Exception as e:
            ethercat_status_message = f"EtherCAT: Errore generico I/O! {e}"
            print(f"[EtherCAT Send Error] Errore generico durante l'invio della tensione: {e}")
            # In caso di errore generico, chiudi e forza la riconnessione
            try:
                if master: master.close()
            except:
                pass
            master = None
            adecua_slave = None
            return False


# --- FINE SEZIONE ETHERCAT SPECIFICA ---

# Parametri del controllo ventola
MAX_KMH = 10.0
MAX_VOLTAGE = 10.0  # Per EL4001, 0-10V
LOG_FILE = "logs/controllo_log.csv"


def log_action(kmh, voltage):
    """Registra l'azione (velocità e tensione) nel file di log."""
    timestamp = datetime.datetime.now().isoformat()
    os.makedirs("logs", exist_ok=True)
    with open(LOG_FILE, mode='a', newline='') as f:
        writer = csv.writer(f, delimiter=';')
        writer.writerow([timestamp, f"{kmh:.2f}", f"{voltage:.2f}"])


def calculate_voltage(kmh):
    """Calcola la tensione necessaria in base alla velocità in km/h."""
    kmh = max(0.0, min(kmh, MAX_KMH))
    voltage = (kmh / MAX_KMH) * MAX_VOLTAGE
    return voltage


app = dash.Dash(__name__)
app.title = "Controllo Ventola ADECUA (Beckhoff EtherCAT)"

app.layout = html.Div([
    html.H2("Controllo Ventola ADECUA (Beckhoff EtherCAT)"),

    html.Label("Inserisci velocità (km/h):"),
    dcc.Input(id='input-kmh', type='number', min=0, max=MAX_KMH, step=0.1, value=0),
    html.Button("Applica Velocità", id='apply-button', n_clicks=0),
    html.Button("Stop Ventola (0 km/h)", id='stop-button', n_clicks=0, style={'marginLeft': '10px'}),
    html.Button("Riconnetti EtherCAT", id='reconnect-ethercat-button', n_clicks=0, style={'marginLeft': '10px'}),

    html.Div(id='output-status-kmh', style={'marginTop': '20px'}),
    html.Div(id='output-status-volt'),
    html.Div(id='ethercat-connection-status', style={'color': 'blue', 'marginTop': '10px', 'fontWeight': 'bold'}),
    # Stato della connessione EtherCAT

    html.Hr(),
    html.H4("Storico delle tensioni inviate"),
    dcc.Graph(id='grafico-log'),
    dcc.Interval(id="interval-update-graph", interval=5000, n_intervals=0),  # Aggiorna il grafico ogni 5 secondi
    dcc.Interval(id="interval-check-ethercat", interval=2000, n_intervals=0),
    # Controlla e tenta riconnessione ogni 2 secondi
])


# Callback per la gestione della velocità e dell'invio EtherCAT
@app.callback(
    Output('output-status-kmh', 'children'),
    Output('output-status-volt', 'children'),
    Output('ethercat-connection-status', 'children', allow_duplicate=True),
    # Permetti duplicati per update da altri callbacks
    Input('apply-button', 'n_clicks'),
    Input('stop-button', 'n_clicks'),
    State('input-kmh', 'value'),
    prevent_initial_call=True
)
def handle_fan_control(apply_clicks, stop_clicks, kmh_value):
    ctx = dash.callback_context
    triggered_id = ctx.triggered[0]['prop_id']

    global master, adecua_slave, ethercat_status_message

    kmh_to_send = 0.0
    voltage_to_send = 0.0

    if triggered_id == 'stop-button.n_clicks':
        kmh_to_send = 0.0
        voltage_to_send = 0.0
        output_kmh_msg = "🛑 Ventola fermata"
        output_volt_msg = "🔌 Tensione inviata: 0.00 V"
    else:  # apply-button.n_clicks
        kmh_to_send = kmh_value
        voltage_to_send = calculate_voltage(kmh_value)
        output_kmh_msg = f"✅ Velocità impostata: {kmh_to_send:.2f} km/h"
        output_volt_msg = f"🔌 Tensione da inviare: {voltage_to_send:.2f} V"

    print(
        f"\n[Callback handle_fan_control] Tentativo di invio. Velocità: {kmh_to_send:.2f}, Tensione: {voltage_to_send:.2f}")
    send_success = send_to_device(voltage_to_send)

    if not send_success:
        output_volt_msg += " (Invio EtherCAT fallito!)"

    log_action(kmh_to_send, voltage_to_send)

    return output_kmh_msg, output_volt_msg, ethercat_status_message


# Callback per il pulsante di riconnessione manuale
@app.callback(
    Output('ethercat-connection-status', 'children', allow_duplicate=True),
    Input('reconnect-ethercat-button', 'n_clicks'),
    prevent_initial_call=True
)
def reconnect_ethercat_manual(n_clicks):
    if n_clicks is None or n_clicks == 0:
        raise dash.exceptions.PreventUpdate

    global ethercat_status_message

    print(f"\n[Callback reconnect_ethercat_manual] Pulsante Riconnetti premuto.")
    with ethercat_lock:
        if initialize_ethercat_device_logic():
            ethercat_status_message = "EtherCAT: Riconnesso e in OPERATIONAL."
            print("[EtherCAT] Riconnessione manuale riuscita.")
        else:
            ethercat_status_message = "EtherCAT: ERRORE riconnessione manuale!"
            print("[EtherCAT] Riconnessione manuale fallita.")

    return ethercat_status_message


# Callback per il controllo periodico dello stato EtherCAT e auto-riconnessione
@app.callback(
    Output('ethercat-connection-status', 'children', allow_duplicate=True),  # Permetti duplicati
    Input('interval-check-ethercat', 'n_intervals'),
    prevent_initial_call='initial_duplicate'
)
def check_ethercat_status(n_intervals):
    global master, adecua_slave, ethercat_status_message

    # Non bloccare l'UI se la riconnessione richiede tempo.
    # Questo callback si occupa di mantenere lo stato.
    with ethercat_lock:
        current_state_ok = (master and master.is_state(pysoem.OPERATIONAL_STATE) and
                            adecua_slave and adecua_slave.state == pysoem.OPERATIONAL_STATE)

        if not current_state_ok:
            print(
                f"\n[Callback check_ethercat_status] EtherCAT non in stato OK. Master: {master is not None}, Slave: {adecua_slave is not None}. Tentativo di inizializzazione/riconnessione...")
            if initialize_ethercat_device_logic():
                ethercat_status_message = "EtherCAT: Connesso e in OPERATIONAL."
                print("[EtherCAT] Connessione ristabilita tramite controllo periodico.")
            else:
                ethercat_status_message = f"EtherCAT: Disconnesso o Errore durante riconnessione! ({time.strftime('%H:%M:%S')})"
                print(
                    f"[EtherCAT] Fallimento connessione/riconnessione periodica. Messaggio: {ethercat_status_message}")
        else:
            # Se è già in OPERATIONAL, mantieni lo stato OK
            if "Connesso e in OPERATIONAL" not in ethercat_status_message:  # Evita di sovrascrivere messaggi più specifici
                ethercat_status_message = "EtherCAT: Connesso e in OPERATIONAL."
            print(
                f"[Callback check_ethercat_status] EtherCAT in stato OK. Messaggio corrente: {ethercat_status_message}")

    return ethercat_status_message


@app.callback(
    Output("grafico-log", "figure"),
    Input("interval-update-graph", "n_intervals")
)
def update_graph(n):
    import plotly.graph_objs as go
    timestamps, kmhs, volts = [], [], []
    if os.path.exists(LOG_FILE):
        with open(LOG_FILE, newline='') as f:
            reader = csv.reader(f, delimiter=';')
            for row in reader:
                try:
                    timestamps.append(row[0])
                    kmhs.append(float(row[1]))
                    volts.append(float(row[2]))
                except (ValueError, IndexError) as e:
                    print(f"Errore nella lettura della riga del log '{row}': {e}")
                    continue
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
    print("Avvio dell'applicazione Dash.")
    print("La connessione EtherCAT verrà gestita dal callback periodico.")
    print("Assicurati che il terminale sia eseguito come Amministratore (obbligatorio).")
    app.run_server(host='127.0.0.1', port=8050, debug=False)  # Mantenuto debug=False