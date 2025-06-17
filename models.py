from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, Enum, ForeignKey, Date
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
from sqlalchemy import ForeignKey
from uuid import uuid4
import enum

Base = declarative_base()

class RideStatus(enum.Enum):
    requested = "requested"
    accepted = "accepted"
    in_progress = "in_progress"
    completed = "completed"
    cancelled = "cancelled"

class User(Base):
    __tablename__ = "users"

    id = Column(String, primary_key=True)
    name = Column(String)
    role = Column(Enum("rider", "driver", name="user_roles"))
    phone_number = Column(String)
    created_at = Column(DateTime)

class Ride(Base):
    __tablename__ = "rides"

    id = Column(String, primary_key=True)
    rider_id = Column(String, ForeignKey("users.id"))
    driver_id = Column(String, ForeignKey("users.id"), nullable=True)
    pickup_address = Column(String)
    pickup_lat = Column(Float)
    pickup_lng = Column(Float)
    dropoff_address = Column(String)
    dropoff_lat = Column(Float)
    dropoff_lng = Column(Float)
    distance_m = Column(Integer)
    duration_s = Column(Integer)
    summary = Column(String)
    fare_estimate = Column(Integer)
    status = Column(Enum(RideStatus))
    created_at = Column(DateTime)
    accepted_at = Column(DateTime, nullable=True)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)

class LocationUpdate(Base):
    __tablename__ = "location_updates"

    id = Column(String, primary_key=True)
    ride_id = Column(String, ForeignKey("rides.id"))
    driver_id = Column(String, ForeignKey("users.id"))
    lat = Column(Float)
    lng = Column(Float)
    timestamp = Column(DateTime)

class DriverProfile(Base):
    __tablename__ = "driver_profiles"

    id = Column(String, primary_key=True, default=lambda: str(uuid4()))
    user_id = Column(String, ForeignKey("users.id"), unique=True)

    name = Column(String, nullable=False)
    license_number = Column(String, nullable=False)
    license_expiry = Column(Date, nullable=False)

    vehicle_type = Column(String)
    vehicle_plate = Column(String)
    capacity = Column(Integer, default=4)
    current_load = Column(Integer, default=0)

    max_detour_minutes = Column(Integer, default=10)

    user = relationship("User", backref="profile")


