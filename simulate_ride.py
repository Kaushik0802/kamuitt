import requests
import uuid
import os
from dotenv import load_dotenv
from datetime import datetime, UTC
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from models import Ride, RideStatus, User
from sqlalchemy.exc import IntegrityError

# Load environment variables
load_dotenv()
GOOGLE_KEY = os.getenv("GOOGLE_MAPS_API_KEY")
DATABASE_URL = os.getenv("DATABASE_URL")

# -------------------------
# Brazos County Locations
# -------------------------
pickup = {
    "lat": 30.6127,
    "lng": -96.3414,
    "address": "Memorial Student Center, Texas A&M University"
}

dropoff = {
    "lat": 30.6193,
    "lng": -96.3422,
    "address": "Northgate District, College Station TX"
}

# -------------------------------
# Get Route from Google Maps
# -------------------------------
def get_route(pickup, dropoff):
    url = "https://maps.googleapis.com/maps/api/directions/json"
    params = {
        "origin": f"{pickup['lat']},{pickup['lng']}",
        "destination": f"{dropoff['lat']},{dropoff['lng']}",
        "mode": "driving",
        "key": GOOGLE_KEY
    }
    response = requests.get(url, params=params)
    data = response.json()

    if not data["routes"]:
        raise Exception("No route found.")

    leg = data["routes"][0]["legs"][0]
    return {
        "distance": leg["distance"]["value"],   # in meters
        "duration": leg["duration"]["value"],   # in seconds
        "summary": data["routes"][0]["summary"]
    }

# -----------------------------------
# Insert Simulated Rider If Needed
# -----------------------------------
def insert_simulated_user(session):
    rider_id = "rider-sim-1"
    existing = session.query(User).filter_by(id=rider_id).first()
    if not existing:
        user = User(
            id=rider_id,
            name="Simulated Rider",
            role="rider",
            phone_number="0000000000",
            created_at=datetime.now(UTC)
        )
        session.add(user)
        try:
            session.commit()
            print("Simulated rider inserted.")
        except IntegrityError:
            session.rollback()
            print("Simulated rider already exists (race condition).")
    else:
        print("ℹSimulated rider already exists.")

# -------------------------------------
# Insert Ride Into PostgreSQL Table
# -------------------------------------
def insert_ride(route_data):
    engine = create_engine(DATABASE_URL)
    Session = sessionmaker(bind=engine)
    session = Session()

    # Ensure the simulated rider exists
    insert_simulated_user(session)

    ride = Ride(
        id=str(uuid.uuid4()),
        rider_id="rider-sim-1",
        driver_id=None,
        pickup_address=pickup["address"],
        pickup_lat=pickup["lat"],
        pickup_lng=pickup["lng"],
        dropoff_address=dropoff["address"],
        dropoff_lat=dropoff["lat"],
        dropoff_lng=dropoff["lng"],
        distance_m=route_data["distance"],
        duration_s=route_data["duration"],
        summary=route_data["summary"],
        fare_estimate=int((route_data["distance"] / 1000) * 1.5 * 100),  # in cents
        status=RideStatus.requested,
        created_at=datetime.now(UTC),
        accepted_at=None,
        completed_at=None
    )

    session.add(ride)
    session.commit()
    print("Ride inserted:", ride.id)  # must be before session.close()
    session.close()

# ---------------------------
# Run the Simulation
# ---------------------------
if __name__ == "__main__":
    print("Simulating ride...")
    route = get_route(pickup, dropoff)
    insert_ride(route)
    print("Ride simulation complete!")