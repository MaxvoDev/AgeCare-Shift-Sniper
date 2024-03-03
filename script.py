from datetime import datetime
from geopy.geocoders import Nominatim
from geopy.distance import geodesic
import requests
from bs4 import BeautifulSoup
import threading
import random 
import json
import time
import tkinter as tk 
from tkinter import ttk
import re

file_path = "distance.json"
result_path = "shift.json"
config_path = "config.json"
max_offset = 0.01
num_coordinates = 20
shift_list = []
previous_shift_list = []
distance_list = {}
lock  = threading.Lock()


def sendTelegram(msg_body):
    global botToken, chatId

    try:
        base_url = 'https://api.telegram.org/bot' + botToken + '/sendMessage'
        parameters = {
            'chat_id' : chatId,
            'text' : msg_body
        }
        resp = requests.get(base_url, data = parameters)

    except Exception as e:
        print(account['username'] + ' Send Message Failed...Retrying\n')
        sendTelegram(msg_body)

def generate_random_coordinates(base_address, max_offset, num_coordinates):
    geolocator = Nominatim(user_agent="address_locator")
    location = geolocator.geocode(base_address)
    if location is None:
        raise ValueError("Invalid base address")
    
    base_latitude, base_longitude = location.latitude, location.longitude

    coordinates_list = []
    for _ in range(num_coordinates):
        random_latitude_offset = random.uniform(-max_offset, max_offset)
        random_longitude_offset = random.uniform(-max_offset, max_offset)
        
        new_latitude = base_latitude + random_latitude_offset
        new_longitude = base_longitude + random_longitude_offset
        
        coordinates_list.append((new_latitude, new_longitude))
    
    return coordinates_list

def get_coordinates(address):
    geolocator = Nominatim(user_agent="address_locator")
    location = geolocator.geocode(address)
    if location:
        return location.latitude, location.longitude
    else:
        print(f"Unable to find coordinates for address: {address}")
        return None, None


def calculate_distance(home_address, target_suburb):
    home_latitude, home_longitude = random.choice(random_coordinates)
    target_latitude, target_longitude = get_coordinates(target_suburb)

    if home_latitude is not None and target_latitude is not None:
        distance = geodesic((home_latitude, home_longitude), (target_latitude, target_longitude)).kilometers
        return distance
    else:
        return None


def process_page(session, page):
    global shift_list, distance_list 

    response = session.get(f"https://altaira.thisplanet.com.au/nurse/shiftrequests?page={page}")
    soup = BeautifulSoup(response.text, "html.parser")
    rows = soup.select("table > tr:not(:first-child)")

    for row in rows:
        table_data = row.select("td")
        shift_date = table_data[0].text.strip()
        target_name = table_data[1].text.strip()
        
        start_time = table_data[2].text.strip()
        end_time =  table_data[3].text.strip()
        start_datetime = datetime.strptime(start_time, "%H:%M")
        end_datetime = datetime.strptime(end_time, "%H:%M")
        duration_seconds = (end_datetime - start_datetime).total_seconds()

        shift_time = start_time + " - " + end_time
        target_location = table_data[-3].text.strip() + ", South Australia"
        target_location = target_location.lower()
        href = table_data[-1].select("a")[0]["href"]
        if target_location in distance_list:
            distance = distance_list[target_location]
        else:
            try: 
                distance = calculate_distance(home_address, target_location)
                distance_list[target_location]  = distance
            except Exception as e:
                distance = 1
        if not distance:
            distance = 1

        with lock:
            shift_list.append({
                "name": target_name,
                "shift date": shift_date,
                "end time": datetime.strptime(end_time, "%H:%M"),
                "total seconds": duration_seconds,
                "time": shift_time,
                "place": target_location,
                "distance": distance,
                "link": href
            })

def snipe_it(session, shift):
    pattern = r"id=(\d+)&addtoroster=true"
    matches = re.search(pattern, shift["link"])
    shift_id = matches.group(1)
    link = "https://altaira.thisplanet.com.au" + shift["link"]
    data = {
        "id": shift_id,
        "comments": ""
    }

    response = session.post(link, data)
    if response.status_code == 200:
        return True
    return False

def refreshData():
    global max_distance, log_text, shift_list, minshift_seconds, snipe_listday, is_snipingshift, done_snipe, snipe_maxdistance, config, max_endtime

    data = config["account"]

    session = requests.Session()
    response = session.post('https://altaira.thisplanet.com.au/', data)
    if response.status_code == 200:

        data = {
            "start_date": "27/02/2024",
            "end_date": "01/12/2024",
            "AnyTime": "true",
            "AnyTime": "false",
            "hospitalId": "0",
            "nurseTypeId": "0",
            "shiftTypeId": "0",
            "department": "All Departments"
        }
        response = session.post("https://altaira.thisplanet.com.au/nurse/shiftrequests?page=1", data)
        if response.status_code == 200:
            soup = BeautifulSoup(response.text, "html.parser")
            paginations = soup.select("div.pager > a")
            total_page = int(paginations[-1]["href"].split("?page=")[1])

            threads = []
            for page in range(min(6, total_page)):
                thread = threading.Thread(target=process_page, args=(session, page))
                thread.start()
                threads.append(thread)

            for thread in threads:
                thread.join()

            unique_shift = []
            links = previous_shift_list
            for item in shift_list:
                special_day = ["SAT", "SUN"]

                if is_snipingshift:
                    day_index = next((i for i, day in enumerate(snipe_listday) if day in item["shift date"]), -1)

                    if (day_index > -1 and not done_snipe.get(snipe_listday[day_index]) 
                    and item["total seconds"] > minshift_seconds and item["distance"] < snipe_maxdistance
                    and item["end time"] < max_endtime):
                        done_snipe[snipe_listday[day_index]] = True

                        is_succeed = snipe_it(session, item)

                        if is_succeed:
                            log_text.insert("1.0", f"""
SNIPE SUCCEED !!!!
NAME: {item["name"].upper()}
SHIFT DATE: {item["shift date"]}
TOTAL HOURS: {item["total seconds"] / 3600} hours
TIME: {item["time"]}
PLACE: {item["place"].upper()}
GOOGLE MAP: { "https://www.google.com/maps/dir/14+Caswell+Cct,+Mawson+Lakes+SA+5095/" + '+'.join(item["place"].split())}
LINK: {"https://altaira.thisplanet.com.au" + item["link"]} \n\n 
                            """)

                            sendTelegram(f"""
SNIPE SUCCEED !!!!
NAME: {item["name"].upper()}
SHIFT DATE: {item["shift date"]}
TOTAL HOURS: {item["total seconds"] / 3600} hours
TIME: {item["time"]}
PLACE: {item["place"].upper()}
GOOGLE MAP: { "https://www.google.com/maps/dir/14+Caswell+Cct,+Mawson+Lakes+SA+5095/" + '+'.join(item["place"].split())}
LINK: {"https://altaira.thisplanet.com.au" + item["link"]} \n\n 
                            """)

                is_special = any(day in item["shift date"].upper() for day in special_day)
                if (is_special or item["distance"] < max_distance) and item["link"] not in links:
                    links.append(item["link"])
                    unique_shift.append(item)

            log_text.insert("1.0", f"""
Total Shift Got: {len(shift_list)}
Total New Shift: {len(unique_shift)}            
            """)

            sorted_shift_list = sorted(unique_shift, key=lambda x: x["distance"])

            def chunk_list(lst, chunk_size):
                return [lst[i:i+chunk_size] for i in range(0, len(lst), chunk_size)]

            chunked_list = chunk_list(sorted_shift_list, 10)

            message = f"""
❤️❤️❤️❤️❤️❤️❤️❤️❤️❤️❤️❤️❤️❤️❤️❤️❤️❤️
❤️❤️❤️❤️❤️❤️❤️❤️❤️❤️❤️❤️❤️❤️❤️❤️❤️❤️
❤️❤️❤️❤️❤️❤️❤️❤️❤️❤️❤️❤️❤️❤️❤️❤️❤️❤️
❤️❤️❤️ UPDATE LASTEST SHIFT EVERY 1 MINUTES
❤️❤️❤️ ONLY SHIFT LESS THAN 60 KM ❤️❤️❤️❤️
❤️❤️❤️❤️❤️❤️❤️❤️❤️❤️❤️❤️❤️❤️❤️❤️❤️❤️
❤️❤️❤️❤️❤️❤️❤️❤️❤️❤️❤️❤️❤️❤️❤️❤️❤️❤️
            """
            # Process each chunk
            for chunk in chunked_list:
                for item in chunk:
                    message += f"""
NAME: {item["name"].upper()}
SHIFT DATE: {item["shift date"]}
TOTAL HOURS: {item["total seconds"] / 3600} hours
TIME: {item["time"]}
PLACE: {item["place"].upper()}
GOOGLE MAP: { "https://www.google.com/maps/dir/14+Caswell+Cct,+Mawson+Lakes+SA+5095/" + '+'.join(item["place"].split())}
LINK: {"https://altaira.thisplanet.com.au" + item["link"]} \n\n 
                    """
                
                sendTelegram(message)
                message = ""

            with open(file_path, "w") as json_file:
                json.dump(distance_list, json_file, indent=4)

            with open(result_path, "w") as json_file:
                json.dump(links, json_file, indent=4)

            with open(config_path, "w") as json_file:
                json.dump(config, json_file, indent=4)


def snipe_shift():
    global is_running, config
    global max_distance_entry, checking_interval_entry, bottoken_entry, home_address_entry, groupid_entry, log_text, snipe_maxdistance_entry
    global botToken, chatId, home_address, max_distance
    global random_coordinates, max_offset, num_coordinates
    global auto_snipe_var, minhours_shift_entry, snipe_list_entry, max_endtime_entry
    global minshift_seconds, snipe_listday, is_snipingshift
    global done_snipe, snipe_maxdistance, max_endtime

    max_endtime = datetime.strptime(max_endtime_entry.get(), "%H:%M")
    snipe_maxdistance = int(snipe_maxdistance_entry.get())
    done_snipe = config["is_donesnipe"]
    is_running = True  
    botToken = bottoken_entry.get()
    chatId = groupid_entry.get()
    home_address = home_address_entry.get()
    max_distance = int(max_distance_entry.get())
    second = int(checking_interval_entry.get())
    minshift_seconds = int(minhours_shift_entry.get()) * 3600
    snipe_listday = snipe_list_entry.get().split("|")
    is_snipingshift = auto_snipe_var.get()

    random_coordinates = generate_random_coordinates(home_address, max_offset, num_coordinates)

    while is_running:
        shift_list = []

        log_text.insert("1.0", f"""
Re-try Getting Newest Data - Running The Script Every {second} Seconds
Max Distance: {max_distance} Kilometers            
        """)
        
        refreshData()
        time.sleep(second)

    print("Program Ended !!!")

def start():
    is_running = True 
    threading.Thread(target=snipe_shift).start()

def stop():
    global is_running
    is_running = False

def init():
    global file_path, result_path, config_path
    global distance_list, previous_shift_list, config 

    with open(file_path, "r") as json_file:
        distance_list = json.load(json_file)

    with open(result_path, "r") as json_file:
        previous_shift_list = json.load(json_file)

    with open(config_path, "r") as json_file:
        config = json.load(json_file)


def draw():
    global bottoken_frame, bottoken_entry, groupid_frame, groupid_entry
    global homeaddress_frame, home_address_entry, maxdistance_frame, max_distance_entry, snipe_maxdistance_entry, max_endtime_entry
    global checking_interval_frame, checking_interval_entry, auto_snipe_frame
    global auto_snipe_var, auto_snipe_checkbox, snipe_list_frame, snipe_list_entry
    global minhours_shift_frame, minhours_shift_entry, start_button, stop_button
    global log_text
    global config

    root = tk.Tk()
    root.title("Aged Care Shift Sniper !!!")
    root.geometry("800x600")

    style = ttk.Style(root)
    root.tk.call("source", "forest-light.tcl")
    root.tk.call("source", "forest-dark.tcl")
    style.theme_use("forest-dark")

    frame = ttk.Frame(root)
    frame.pack(fill=tk.BOTH, expand=True)

    bottoken_frame = ttk.LabelFrame(frame, text="Telegram Bot Token")
    bottoken_frame.grid(row=0, column=0)

    bottoken_entry = ttk.Entry(bottoken_frame)
    bottoken_entry.insert(0, config["botToken"])
    bottoken_entry.grid(row=0, column=0, sticky="ew")

    groupid_frame = ttk.LabelFrame(frame, text="Telegram Group ID")
    groupid_frame.grid(row=1, column=0)

    groupid_entry = ttk.Entry(groupid_frame)
    groupid_entry.insert(0, config["chatId"])
    groupid_entry.grid(row=0, column=0, sticky="ew")

    homeaddress_frame = ttk.LabelFrame(frame, text="Home Address")
    homeaddress_frame.grid(row=2, column=0)

    home_address_entry = ttk.Entry(homeaddress_frame)
    home_address_entry.insert(0, config["home_address"])
    home_address_entry.grid(row=0, column=0, sticky="ew")

    maxdistance_frame = ttk.LabelFrame(frame, text="Max Distance (in Kilometers)")
    maxdistance_frame.grid(row=3, column=0)

    max_distance_entry = ttk.Entry(maxdistance_frame)
    max_distance_entry.insert(0, "60")
    max_distance_entry.grid(row=0, column=0, sticky="ew")

    checking_interval_frame = ttk.LabelFrame(frame, text="Checking Interval (in Seconds)")
    checking_interval_frame.grid(row=4, column=0)

    checking_interval_entry = ttk.Entry(checking_interval_frame)
    checking_interval_entry.insert(0, config["checking_interval"])
    checking_interval_entry.grid(row=0, column=0, sticky="ew")

    auto_snipe_frame = ttk.LabelFrame(frame, text="Auto Snipe Shift")
    auto_snipe_frame.grid(row=5, column=0)
    
    auto_snipe_var = tk.BooleanVar()
    auto_snipe_checkbox = ttk.Checkbutton(auto_snipe_frame, variable=auto_snipe_var)
    auto_snipe_checkbox.grid(row=0, column=0, sticky="ew")

    snipe_list_frame = ttk.LabelFrame(frame, text="Date want to Snipe (Ex: 25|26)")
    snipe_list_frame.grid(row=6, column=0)

    snipe_list_entry = ttk.Entry(snipe_list_frame)
    snipe_list_entry.insert(0, "25|26")
    snipe_list_entry.grid(row=0, column=0, sticky="ew")

    snipe_maxdistance_frame = ttk.LabelFrame(frame, text="Snipe Max Distance (in Kilometers)")
    snipe_maxdistance_frame.grid(row=7, column=0)

    snipe_maxdistance_entry = ttk.Entry(snipe_maxdistance_frame)
    snipe_maxdistance_entry.insert(0, config["snipe_maxdistance"])
    snipe_maxdistance_entry.grid(row=0, column=0, sticky="ew")

    minhours_shift_frame = ttk.LabelFrame(frame, text="Min Shift Snipe (in Hours)")
    minhours_shift_frame.grid(row=8, column=0)

    minhours_shift_entry = ttk.Entry(minhours_shift_frame)
    minhours_shift_entry.insert(0, config["minhours_shift"])
    minhours_shift_entry.grid(row=0, column=0)

    max_endtime_frame = ttk.LabelFrame(frame, text="Max End Time (in DateTime)")
    max_endtime_frame.grid(row=9, column=0)

    max_endtime_entry = ttk.Entry(max_endtime_frame)
    max_endtime_entry.insert(0, config["max_endtime"])
    max_endtime_entry.grid(row=0, column=0)

    start_button = ttk.Button(frame, text="Start", command=start)
    start_button.grid(row=10, column=0, sticky="ew")

    stop_button = ttk.Button(frame, text="Stop", command=stop)
    stop_button.grid(row=11, column=0, sticky="ew")

    log_text = tk.Text(frame, height=10, width=80)
    log_text.grid(row=0, column=1, rowspan=10, columnspan=100, sticky="nswe", padx=10, pady=10)

    root.mainloop()


if __name__ == "__main__":
    init()
    draw()