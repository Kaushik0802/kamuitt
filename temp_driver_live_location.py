import requests
import time

RIDE_ID = "8323469e-4761-46e2-bfad-3d8850c62d18"  # replace this with your real ride ID
POLL_INTERVAL = 5  # seconds
API_URL = "http://localhost:8000/get_location"

def poll_location():
    try:
        response = requests.get(API_URL, params={"ride_id": RIDE_ID})
        if response.status_code == 200:
            data = response.json()
            lat = data['lat']
            lng = data['lng']
            timestamp = data['timestamp']
            print(f" Driver location: ({lat}, {lng}) at {timestamp}")
        else:
            print(f" No location data. Status: {response.status_code} - {response.text}")
    except Exception as e:
        print(" Error polling:", e)

if __name__ == "__main__":
    print("📡 Starting location polling...")
    while True:
        poll_location()
        time.sleep(POLL_INTERVAL)
