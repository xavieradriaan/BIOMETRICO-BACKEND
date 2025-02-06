import csv
import json
import requests
from requests.auth import HTTPDigestAuth
from collections import defaultdict
from datetime import datetime
from flask import Flask, jsonify, request
from flask_cors import CORS
import time

app = Flask(__name__)
CORS(app)  # Habilitar CORS para todas las rutas

# Configuración de la solicitud para eventos de asistencia
attendance_url = 'http://192.168.42.100/ISAPI/AccessControl/AcsEvent?format=json'
user_info_url = 'http://192.168.42.100/ISAPI/AccessControl/UserInfo/Search?format=json'
headers = {'Content-Type': 'application/json'}
auth = HTTPDigestAuth('admin', 'citell2024.')
search_id = "1"
max_results = 600

# Función para obtener eventos de asistencia
def get_attendance_events(search_result_position, start_time, end_time):
    data = {
        "AcsEventCond": {
            "searchID": search_id,
            "searchResultPosition": search_result_position,
            "maxResults": max_results,
            "major": 5,
            "minor": 38,
            "startTime": start_time,
            "endTime": end_time
        }
    }
    response = requests.post(attendance_url, headers=headers, json=data, auth=auth)
    if response.status_code == 200:
        try:
            return response.json()
        except json.JSONDecodeError:
            print("Error decodificando la respuesta JSON:", response.text)
            return None
    elif response.status_code == 401:
        print("Error en la solicitud: 401 Unauthorized. Verifica las credenciales.")
        return None
    else:
        print("Error en la solicitud:", response.status_code, response.text)
        return None

# Función para obtener información de todos los usuarios
def get_all_users():
    all_users = []
    search_result_position = 0
    retries = 3
    while retries > 0:
        data = {
            "UserInfoSearchCond": {
                "searchID": "1",
                "searchResultPosition": search_result_position,
                "maxResults": 100  # Ajusta este valor según sea necesario
            }
        }
        response = requests.post(user_info_url, headers=headers, json=data, auth=auth)
        if response.status_code == 200:
            response_json = response.json()
            if 'UserInfoSearch' in response_json and 'UserInfo' in response_json['UserInfoSearch']:
                users = response_json['UserInfoSearch']['UserInfo']
                all_users.extend(users)
                search_result_position += len(users)
                if response_json['UserInfoSearch']['responseStatusStrg'] != "MORE":
                    break
            else:
                print("No se encontraron más usuarios o hubo un error en la respuesta.")
                break
        elif response.status_code == 401:
            print("Error en la solicitud: 401 Unauthorized. Verifica las credenciales.")
            break
        else:
            print(f"Error: {response.status_code}")
            print(response.text)
            retries -= 1
            time.sleep(5)  # Esperar 5 segundos antes de reintentar
    return all_users

# Función para verificar si hay "N/A" en el archivo CSV de nombres
def has_na_in_names(csv_filename_names):
    with open(csv_filename_names, mode='r') as file:
        reader = csv.DictReader(file)
        for row in reader:
            if row["Name"] == "N/A":
                return True
    return False

@app.route('/attendance', methods=['GET'])
def get_attendance():
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    
    if not start_date or not end_date:
        return jsonify({"error": "start_date and end_date are required"}), 400
    
    # Ajustar las fechas para que siempre inicien a las 00:00:00 y terminen a las 23:59:59Z
    start_time = f"{start_date}T00:00:00Z"
    end_time = f"{end_date}T23:59:59Z"
    
    all_events = []
    search_result_position = 0
    while True:
        response_json = get_attendance_events(search_result_position, start_time, end_time)
        if response_json and 'AcsEvent' in response_json and 'InfoList' in response_json['AcsEvent']:
            events = response_json['AcsEvent']['InfoList']
            all_events.extend(events)
            search_result_position += len(events)
            if response_json['AcsEvent']['responseStatusStrg'] != "MORE":
                break
        else:
            print("No se encontraron más eventos o hubo un error en la respuesta.")
            break

    # Agrupar eventos por employeeNoString y fecha
    events_by_employee_and_date = defaultdict(list)
    for event in all_events:
        employee_id = event['employeeNoString']
        event_time = datetime.fromisoformat(event['time'])
        date_str = event_time.date().isoformat()
        events_by_employee_and_date[(employee_id, date_str)].append(event_time)

    # Determinar la primera y última marcación del día para cada empleado y fecha
    attendance_records = []
    for (employee_id, date_str), times in events_by_employee_and_date.items():
        first_check_in = min(times)
        last_check_out = max(times)
        attendance_records.append({
            "Employee ID": employee_id,
            "Date": date_str,
            "First Check-In Time": first_check_in.isoformat(),
            "Last Check-Out Time": last_check_out.isoformat()
        })

    # Exportar los resultados a un archivo CSV
    csv_filename = 'attendance_records.csv'
    with open(csv_filename, mode='w', newline='') as file:
        writer = csv.writer(file)
        writer.writerow(["Employee ID", "Date", "First Check-In Time", "Last Check-Out Time"])
        for record in attendance_records:
            writer.writerow([record["Employee ID"], record["Date"], record["First Check-In Time"], record["Last Check-Out Time"]])

    print(f"Los resultados se han exportado a {csv_filename}")

    # Obtener todos los usuarios y exportar a un archivo CSV
    csv_filename_names = 'nombres_employeeid.csv'
    while True:
        all_users = get_all_users()
        with open(csv_filename_names, mode='w', newline='') as file:
            writer = csv.writer(file)
            writer.writerow(["Employee ID", "Name"])
            for user in all_users:
                employee_id = user.get('employeeNoString', user.get('employeeNo', 'N/A'))
                name = user.get('name', 'N/A')
                writer.writerow([employee_id, name])
        print(f"Los resultados se han exportado a {csv_filename_names}")

        # Verificar si hay "N/A" en el archivo CSV de nombres
        if not has_na_in_names(csv_filename_names):
            break
        print("Se encontraron 'N/A' en los nombres, reintentando la obtención de nombres...")

    # Crear un diccionario de nombres de empleados
    employee_names = {}
    with open(csv_filename_names, mode='r') as file:
        reader = csv.DictReader(file)
        for row in reader:
            employee_id = row["Employee ID"]
            name = row["Name"]
            employee_names[employee_id] = name

    # Leer el archivo CSV temporal y actualizarlo con los nombres de los empleados
    attendance_records_with_names = []
    with open(csv_filename, mode='r') as file:
        reader = csv.DictReader(file)
        for row in reader:
            employee_id = row["Employee ID"]
            name = employee_names.get(employee_id, 'N/A')
            attendance_records_with_names.append({
                "Employee ID": employee_id,
                "Name": name,
                "Date": row["Date"],
                "First Check-In Time": row["First Check-In Time"],
                "Last Check-Out Time": row["Last Check-Out Time"]
            })

    # Exportar los resultados a un nuevo archivo CSV
    csv_with_names_filename = 'attendance_records_with_names.csv'
    with open(csv_with_names_filename, mode='w', newline='') as file:
        fieldnames = ["Employee ID", "Name", "Date", "First Check-In Time", "Last Check-Out Time"]
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        for record in attendance_records_with_names:
            writer.writerow(record)

    print(f"Los resultados con nombres se han exportado a {csv_with_names_filename}")

    return jsonify(attendance_records_with_names)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
