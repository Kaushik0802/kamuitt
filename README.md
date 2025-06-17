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

2. Configure PostgreSQL
Create a local PostgreSQL DB and set the connection string in .env:

bash
Copy
Edit
DATABASE_URL=postgresql://user:password@localhost:5432/kamuit
Then run:

bash
Copy
Edit
python create_db.py
3. Start the Backend
bash
Copy
Edit
uvicorn main:app --reload
Visit: http://localhost:8000/docs

📡 Key API Endpoints
Endpoint	Purpose
POST /request_ride	Create a ride
POST /assign_driver	Assign a driver manually
POST /start_ride	Mark ride as in_progress
POST /update_status	Change ride status
POST /update_location	Push driver GPS
GET /get_location	Get latest driver location
GET /admin_dashboard	Admin stats
POST /find_nearby_driver	Get closest driver

📍 Location Coverage
Uses real Brazos County / College Station addresses

Tuned for local pickup/dropoff points (e.g., TAMU MSC, Northgate)

📦 Roadmap
 Rider-driver flow

 Live driver tracking

 Ride status management

 Route optimization by economic value

 Driver scoring & ETA-based assignment

 Frontend map visualization (Leaflet / Folium)

 Deployment to cloud (Render / Railway)



