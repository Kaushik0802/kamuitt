from fastapi import FastAPI, Depends, HTTPException, Body
from sqlalchemy.orm import Session
from pydantic import BaseModel
from database import SessionLocal
from models import Ride, RideStatus, User, LocationUpdate, DriverProfile, DetourScoreLog
import uuid
import requests
from datetime import datetime, UTC
import os
from dotenv import load_dotenv

load_dotenv()
GOOGLE_KEY = os.getenv("GOOGLE_MAPS_API_KEY")

app = FastAPI()

# -----------------------
# DB Session Dependency
# -----------------------
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# -----------------------
# Request Schemas
# -----------------------
class Location(BaseModel):
    lat: float
    lng: float
    address: str

class RideRequest(BaseModel):
    rider_id: str
    pickup: Location
    dropoff: Location

class DriverOnboarding(BaseModel):
    user_id: str
    name: str
    license_number: str
    license_expiry: str  # format: "YYYY-MM-DD"
    vehicle_type: str
    vehicle_plate: str
    capacity: int = 4
    max_detour_minutes: int = 10

# -----------------------
# Ride Status Enum
# -----------------------
class SetDriverLocationRequest(BaseModel):
    driver_id: str
    lat: float
    lng: float

class Location(BaseModel):
    lat: float
    lng: float
    address: str

# -----------------------
# Home Check
# -----------------------
@app.get("/")
def home():
    return {"message": "Kamuit backend is running"}

# -----------------------
#  Set Driver Location
# -----------------------
@app.post("/set_driver_location")
def set_driver_location(data: SetDriverLocationRequest, db: Session = Depends(get_db)):
    profile = db.query(DriverProfile).filter_by(user_id=data.driver_id).first()
    if not profile:
        raise HTTPException(status_code=404, detail="Driver not found")

    profile.lat = data.lat
    profile.lng = data.lng
    db.commit()

    return {
        "message": "Driver GPS updated",
        "driver_id": data.driver_id,
        "lat": data.lat,
        "lng": data.lng
    }



# -----------------------
#  Request Ride
# -----------------------
@app.post("/request_ride")
def request_ride(data: RideRequest, db: Session = Depends(get_db)):
    url = "https://maps.googleapis.com/maps/api/directions/json"
    params = {
        "origin": f"{data.pickup.lat},{data.pickup.lng}",
        "destination": f"{data.dropoff.lat},{data.dropoff.lng}",
        "mode": "driving",
        "key": GOOGLE_KEY
    }

    response = requests.get(url, params=params).json()
    if not response.get("routes"):
        raise HTTPException(status_code=400, detail="Route not found")

    leg = response["routes"][0]["legs"][0]
    route_summary = {
        "distance": leg["distance"]["value"],
        "duration": leg["duration"]["value"],
        "summary": response["routes"][0]["summary"]
    }

    fare_estimate = int((route_summary["distance"] / 1000) * 1.5 * 100)  # cents -> requird logicical equation from Managemnt

    ride = Ride(
        id=str(uuid.uuid4()),
        rider_id=data.rider_id,
        driver_id=None,
        pickup_address=data.pickup.address,
        pickup_lat=data.pickup.lat,
        pickup_lng=data.pickup.lng,
        dropoff_address=data.dropoff.address,
        dropoff_lat=data.dropoff.lat,
        dropoff_lng=data.dropoff.lng,
        distance_m=route_summary["distance"],
        duration_s=route_summary["duration"],
        summary=route_summary["summary"],
        fare_estimate=fare_estimate,
        status=RideStatus.requested,
        created_at=datetime.now(UTC)
    )

    db.add(ride)
    db.commit()

    return {
        "ride_id": ride.id,
        "fare_estimate": fare_estimate,
        "summary": route_summary["summary"],
        "distance_m": route_summary["distance"],
        "duration_s": route_summary["duration"]
    }

# -----------------------
# Assign Driver
# -----------------------
@app.post("/assign_driver")
def assign_driver(ride_data: dict = Body(...), db: Session = Depends(get_db)):
    from models import DetourScoreLog

    ride_id = ride_data.get("ride_id")
    ride = db.query(Ride).filter_by(id=ride_id, status=RideStatus.requested).first()
    if not ride:
        raise HTTPException(status_code=404, detail="Ride not found or already matched")

    # Get active driver IDs
    active_driver_ids = db.query(Ride.driver_id).filter(
        Ride.status.in_([RideStatus.accepted, RideStatus.in_progress])
    ).distinct().all()
    active_driver_ids = [d[0] for d in active_driver_ids if d[0]]

    # Get idle, GPS-ready drivers
    candidates = db.query(DriverProfile).filter(
        ~DriverProfile.user_id.in_(active_driver_ids),
        DriverProfile.lat.isnot(None),
        DriverProfile.lng.isnot(None)
    ).all()

    if not candidates:
        raise HTTPException(status_code=503, detail="No available drivers with GPS")

    detour_candidates = []
    for driver in candidates:
        origin = f"{driver.lat},{driver.lng}"
        destination = f"{ride.pickup_lat},{ride.pickup_lng}"

        url = "https://maps.googleapis.com/maps/api/directions/json"
        params = {
            "origin": origin,
            "destination": destination,
            "key": GOOGLE_KEY
        }

        try:
            response = requests.get(url, params=params).json()
            if "routes" not in response or not response["routes"]:
                continue

            detour_duration_s = response["routes"][0]["legs"][0]["duration"]["value"]
            detour_minutes = detour_duration_s / 60.0

            # ⛔ Skip if detour exceeds driver's threshold
            if detour_minutes > driver.max_detour_minutes:
                continue

            detour_candidates.append((driver.user_id, detour_duration_s))
        except Exception:
            continue

    if not detour_candidates:
        raise HTTPException(status_code=503, detail="No suitable driver found (all detours too high?)")

    # Pick driver with lowest detour
    detour_candidates.sort(key=lambda x: x[1])
    chosen_driver_id, best_detour = detour_candidates[0]

    # Assign ride
    ride.driver_id = chosen_driver_id
    ride.status = RideStatus.accepted
    ride.accepted_at = datetime.now(UTC)
    db.commit()

    # Log detour scores
    for driver_id, detour in detour_candidates:
        db.add(DetourScoreLog(
            ride_id=ride.id,
            driver_id=driver_id,
            detour_duration_s=detour,
            was_accepted=1 if driver_id == chosen_driver_id else 0
        ))
    db.commit()

    return {
        "ride_id": ride.id,
        "driver_id": ride.driver_id,
        "detour_duration_s": best_detour,
        "status": ride.status.value
    }


# -----------------------
# Fallback Check
# -----------------------
@app.post("/fallback_check")
def fallback_check(data: dict = Body(...), db: Session = Depends(get_db)):
    ride_id = data.get("ride_id")
    fallback_timeout = data.get("timeout", 30)

    ride = db.query(Ride).filter_by(id=ride_id).first()
    if not ride or ride.status != RideStatus.accepted:
        raise HTTPException(status_code=404, detail="No active ride for fallback check")

    elapsed = (datetime.now(UTC) - ride.accepted_at).total_seconds()
    if elapsed < fallback_timeout:
        return {"status": "waiting", "seconds_since_assignment": elapsed}

    db.query(DetourScoreLog).filter_by(ride_id=ride_id, driver_id=ride.driver_id).update(
        {"was_accepted": -1}
    )
    db.commit()

    ride.driver_id = None
    ride.status = RideStatus.requested
    db.commit()

    return {"status": "fallback_triggered", "elapsed_s": elapsed}

# -----------------------
# Update Driver Location
# -----------------------
@app.post("/update_location")
def update_location(data: dict = Body(...), db: Session = Depends(get_db)):
    ride_id = data.get("ride_id")
    driver_id = data.get("driver_id")
    location = data.get("location")

    if not location or "lat" not in location or "lng" not in location:
        raise HTTPException(status_code=400, detail="Invalid location data")

    ride = db.query(Ride).filter_by(id=ride_id, driver_id=driver_id).first()
    if not ride:
        raise HTTPException(status_code=404, detail="Ride not found or driver mismatch")

    update = LocationUpdate(
        id=str(uuid.uuid4()),
        ride_id=ride_id,
        driver_id=driver_id,
        lat=location["lat"],
        lng=location["lng"],
        timestamp=datetime.now(UTC)
    )

    db.add(update)

    profile = db.query(DriverProfile).filter_by(user_id=driver_id).first()
    if profile:
        profile.lat = location["lat"]
        profile.lng = location["lng"]

    db.commit()

    return {
        "message": "Location updated",
        "ride_id": ride_id,
        "driver_id": driver_id,
        "timestamp": update.timestamp.isoformat()
    }

# -----------------------
# Start Ride
# -----------------------
@app.post("/start_ride")
def start_ride(data: dict = Body(...), db: Session = Depends(get_db)):
    ride_id = data.get("ride_id")
    driver_id = data.get("driver_id")

    ride = db.query(Ride).filter_by(id=ride_id, driver_id=driver_id).first()

    if not ride:
        raise HTTPException(status_code=404, detail="Ride not found or not assigned to driver")

    if ride.status != RideStatus.accepted:
        raise HTTPException(status_code=400, detail="Ride is not in accepted state")

    ride.status = RideStatus.in_progress
    ride.started_at = datetime.now(UTC)  # optional field
    db.commit()

    return {
        "ride_id": ride.id,
        "status": ride.status.value,
        "message": "Ride started"
    }

# -----------------------
# Complete Ride
# -----------------------
@app.post("/complete_ride")
def complete_ride(data: dict = Body(...), db: Session = Depends(get_db)):
    ride_id = data.get("ride_id")
    driver_id = data.get("driver_id")

    ride = db.query(Ride).filter_by(id=ride_id, driver_id=driver_id).first()
    if not ride:
        raise HTTPException(status_code=404, detail="Ride not found or not assigned to driver")

    if ride.status != RideStatus.in_progress:
        raise HTTPException(status_code=400, detail="Ride is not in progress")

    ride.status = RideStatus.completed
    ride.completed_at = datetime.now(UTC)
    db.commit()

    return {
        "ride_id": ride.id,
        "status": ride.status.value,
        "completed_at": ride.completed_at.isoformat()
    }

# -----------------------
# Cancel Ride
# -----------------------
@app.post("/cancel_ride")
def cancel_ride(data: dict = Body(...), db: Session = Depends(get_db)):
    ride_id = data.get("ride_id")
    rider_id = data.get("rider_id")

    ride = db.query(Ride).filter_by(id=ride_id, rider_id=rider_id).first()
    if not ride:
        raise HTTPException(status_code=404, detail="Ride not found or rider mismatch")

    if ride.status in [RideStatus.completed, RideStatus.cancelled]:
        raise HTTPException(status_code=400, detail="Ride already completed or cancelled")

    if ride.status == RideStatus.in_progress:
        raise HTTPException(status_code=403, detail="Cannot cancel a ride in progress")

    ride.status = RideStatus.cancelled
    ride.completed_at = datetime.now(UTC)  # optional reuse of this field
    db.commit()

    return {
        "ride_id": ride.id,
        "status": ride.status.value,
        "message": "Ride has been cancelled"
    }

# -----------------------
# Driver Dashboard
# -----------------------
@app.post("/driver_dashboard")
def driver_dashboard(data: dict = Body(...), db: Session = Depends(get_db)):
    driver_id = data.get("driver_id")

    # Get active ride (if any)
    active_ride = db.query(Ride).filter(
        Ride.driver_id == driver_id,
        Ride.status.in_([RideStatus.accepted, RideStatus.in_progress])
    ).first()

    # Get completed rides
    completed_rides = db.query(Ride).filter(
        Ride.driver_id == driver_id,
        Ride.status == RideStatus.completed
    ).order_by(Ride.completed_at.desc()).all()

    return {
        "active_ride": {
            "ride_id": active_ride.id,
            "status": active_ride.status.value
        } if active_ride else None,

        "completed_rides": [
            {
                "ride_id": r.id,
                "pickup": r.pickup_address,
                "dropoff": r.dropoff_address,
                "fare": r.fare_estimate
            } for r in completed_rides
        ]
    }

# -----------------------
# Rider History
# -----------------------
@app.post("/rider_history")
def rider_history(data: dict = Body(...), db: Session = Depends(get_db)):
    rider_id = data.get("rider_id")

    rides = db.query(Ride).filter(
        Ride.rider_id == rider_id
    ).order_by(Ride.created_at.desc()).all()

    return {
        "rides": [
            {
                "ride_id": r.id,
                "status": r.status.value,
                "fare": r.fare_estimate,
                "pickup": r.pickup_address,
                "dropoff": r.dropoff_address,
                "created_at": r.created_at.isoformat()
            } for r in rides
        ]
    }

# -----------------------
# Driver GPS Initial Ping
# -----------------------
@app.post("/update_location")
def update_location(data: dict = Body(...), db: Session = Depends(get_db)):
    ride_id = data.get("ride_id")
    driver_id = data.get("driver_id")
    location = data.get("location")

    if not location or "lat" not in location or "lng" not in location:
        raise HTTPException(status_code=400, detail="Invalid location data")

    # Optional: validate that driver is currently on this ride
    ride = db.query(Ride).filter_by(id=ride_id, driver_id=driver_id).first()
    if not ride:
        raise HTTPException(status_code=404, detail="Ride not found or driver mismatch")

    update = LocationUpdate(
        id=str(uuid.uuid4()),
        ride_id=ride_id,
        driver_id=driver_id,
        lat=location["lat"],
        lng=location["lng"],
        timestamp=datetime.now(UTC)
    )

    db.add(update)
    db.commit()

    return {
        "message": "Location updated",
        "ride_id": ride_id,
        "driver_id": driver_id,
        "timestamp": update.timestamp.isoformat()
    }

# -----------------------
# Get Driver Location Updates
# -----------------------
@app.get("/get_location")
def get_location(ride_id: str, db: Session = Depends(get_db)):
    latest = db.query(LocationUpdate).filter_by(ride_id=ride_id).order_by(
        LocationUpdate.timestamp.desc()).first()

    if not latest:
        raise HTTPException(status_code=404, detail="No location found for this ride")

    return {
        "ride_id": latest.ride_id,
        "driver_id": latest.driver_id,
        "lat": latest.lat,
        "lng": latest.lng,
        "timestamp": latest.timestamp.isoformat()
    }

# -----------------------
# Admin Dashboard
# -----------------------
@app.get("/admin_dashboard")
def admin_dashboard(db: Session = Depends(get_db)):
    from sqlalchemy import func

    total_rides = db.query(func.count(Ride.id)).scalar()
    completed_rides = db.query(func.count(Ride.id)).filter(Ride.status == RideStatus.completed).scalar()
    cancelled_rides = db.query(func.count(Ride.id)).filter(Ride.status == RideStatus.cancelled).scalar()
    in_progress_rides = db.query(func.count(Ride.id)).filter(Ride.status == RideStatus.in_progress).scalar()

    total_drivers = db.query(func.count(User.id)).filter(User.role == "driver").scalar()
    total_riders = db.query(func.count(User.id)).filter(User.role == "rider").scalar()

    # Drivers currently assigned to accepted/in_progress rides
    active_driver_ids = db.query(Ride.driver_id).filter(
        Ride.status.in_([RideStatus.accepted, RideStatus.in_progress])
    ).distinct().all()
    active_driver_ids = [d[0] for d in active_driver_ids if d[0]]

    idle_drivers = db.query(User).filter(
        User.role == "driver",
        ~User.id.in_(active_driver_ids)
    ).count()

    return {
        "total_rides": total_rides,
        "completed_rides": completed_rides,
        "cancelled_rides": cancelled_rides,
        "in_progress_rides": in_progress_rides,
        "total_drivers": total_drivers,
        "active_drivers": len(active_driver_ids),
        "idle_drivers": idle_drivers,
        "total_riders": total_riders
    }

# -----------------------
# Onboard Driver
# -----------------------
@app.post("/onboard_driver")
def onboard_driver(data: dict = Body(...), db: Session = Depends(get_db)):
    user_id = data.get("user_id")
    user = db.query(User).filter_by(id=user_id, role="driver").first()

    if not user:
        raise HTTPException(status_code=404, detail="Driver user not found")

    # Check if profile already exists
    existing = db.query(DriverProfile).filter_by(user_id=user_id).first()
    if existing:
        raise HTTPException(status_code=400, detail="Driver profile already exists")

    profile = DriverProfile(
        user_id=user_id,
        name=data.get("name"),
        license_number=data.get("license_number"),
        license_expiry=datetime.strptime(data.get("license_expiry"), "%Y-%m-%d").date(),
        vehicle_type=data.get("vehicle_type"),
        vehicle_plate=data.get("vehicle_plate"),
        capacity=data.get("capacity", 4),
        current_load=0,
        max_detour_minutes=data.get("max_detour_minutes", 10)
    )
    db.add(profile)
    db.commit()
    return {"message": "Driver onboarded successfully"}