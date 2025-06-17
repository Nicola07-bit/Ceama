import tkinter as tk

# === Costanti ===
max_kmh = 10.0             # Velocità massima
max_voltage = 12.0         # Tensione massima

# === Funzioni ===

def calculate_voltage_from_kmh(kmh):
    kmh = max(0.0, min(kmh, max_kmh))
    voltage = (kmh / max_kmh) * max_voltage
    return voltage, kmh

def update_display():
    try:
        kmh_input = float(speed_entry.get())
        voltage, kmh = calculate_voltage_from_kmh(kmh_input)
        
        current_speed_label.config(text=f"✅ Velocità impostata: {kmh:.2f} km/h")
        current_voltage_label.config(text=f"🔌 Tensione simulata: {voltage:.2f} V")
        if kmh_input > max_kmh:
            result_label.config(text="ℹ️ Velocità limitata a 10 km/h.")
        else:
            result_label.config(text="")
    except ValueError:
        current_speed_label.config(text="")
        current_voltage_label.config(text="")
        result_label.config(text="⚠ Inserisci un numero valido per la velocità.")

def stop_fan():
    speed_entry.delete(0, tk.END)
    speed_entry.insert(0, "0")
    current_speed_label.config(text="🛑 Ventola fermata (0 km/h)")
    current_voltage_label.config(text="🔌 Tensione simulata: 0.00 V")
    result_label.config(text="")

# === GUI ===

root = tk.Tk()
root.title("Simulatore Controllo Ventola")

# Istruzioni
instruction_label = tk.Label(root, text="Imposta la velocità della ventola (max 10 km/h):", font=("Arial", 14))
instruction_label.pack(pady=10)

# Campo input
speed_entry = tk.Entry(root, font=("Arial", 14), justify="center")
speed_entry.pack(pady=5)

# Pulsanti
button_frame = tk.Frame(root)
button_frame.pack(pady=10)

update_button = tk.Button(button_frame, text="Imposta velocità", command=update_display, font=("Arial", 12), width=18)
update_button.grid(row=0, column=0, padx=5)

stop_button = tk.Button(button_frame, text="Stop Ventola", command=stop_fan, font=("Arial", 12), bg="red", fg="white", width=18)
stop_button.grid(row=0, column=1, padx=5)

# Etichette di output
current_speed_label = tk.Label(root, text="", font=("Arial", 14))
current_speed_label.pack(pady=5)

current_voltage_label = tk.Label(root, text="", font=("Arial", 14))
current_voltage_label.pack(pady=5)

result_label = tk.Label(root, text="", font=("Arial", 12), fg="red")
result_label.pack(pady=5)

# Avvio GUI
root.mainloop()
