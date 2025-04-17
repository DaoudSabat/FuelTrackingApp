import pandas as pd
import requests
from django.conf import settings
from geopy.distance import geodesic
import os
import polyline
from typing import List, Dict, Tuple, Optional

# Constants
VEHICLE_RANGE_MILES = 450  # Maximum miles per full tank
MPG = 10  # Miles per gallon
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CSV_FILE_PATH = os.path.join(BASE_DIR, "api", "fuel-prices-for-be-assessment.csv")
GOOGLE_MAPS_API_KEY = settings.GOOGLE_MAPS_API_KEY
DIRECTIONS_API_URL = "https://maps.googleapis.com/maps/api/directions/json"
GEOCODE_API_URL = "https://maps.googleapis.com/maps/api/geocode/json"

# Cached gas stations DataFrame and precomputed data
_gas_stations_cache = None
_city_state_cache = {}  # Cache for lat/lon to city/state lookups

def load_gas_stations() -> pd.DataFrame:
    """Loads and caches gas station data from CSV."""
    global _gas_stations_cache
    if _gas_stations_cache is not None:
        return _gas_stations_cache

    try:
        df = pd.read_csv(CSV_FILE_PATH, delimiter=",")
        df.columns = [col.strip().lower() for col in df.columns]
        required_cols = {"city", "state"}
        if not required_cols.issubset(df.columns):
            raise KeyError(f"Missing required columns: {required_cols - set(df.columns)}")
        
        df["city"] = df["city"].str.strip().str.lower()
        df["state"] = df["state"].str.strip().str.upper()
        _gas_stations_cache = df
        print(f"✅ Loaded {len(df)} gas stations from {CSV_FILE_PATH}")
        return df
    except FileNotFoundError as e:
        raise FileNotFoundError(f"CSV file not found at {CSV_FILE_PATH}") from e
    except Exception as e:
        raise Exception(f"Error loading CSV: {e}") from e

def get_city_state_from_coordinates(lat: float, lon: float) -> Tuple[Optional[str], Optional[str]]:
    """Converts lat/lon to city/state using Google Maps API with caching."""
    key = (round(lat, 4), round(lon, 4))  # Reduce precision to avoid redundant calls
    if key in _city_state_cache:
        return _city_state_cache[key]

    params = {"latlng": f"{lat},{lon}", "key": GOOGLE_MAPS_API_KEY}
    try:
        response = requests.get(GEOCODE_API_URL, params=params, timeout=5)
        data = response.json()
        if data.get("status") == "OK":
            city, state = None, None
            for component in data["results"][0]["address_components"]:
                if "locality" in component["types"]:
                    city = component["long_name"].strip().lower()
                if "administrative_area_level_1" in component["types"]:
                    state = component["short_name"].strip().upper()
            if city and state:
                print(f"✅ Resolved ({lat}, {lon}) to {city}, {state}")
                _city_state_cache[key] = (city, state)
                return city, state
        print(f"⚠️ Geocode failed: {data.get('error_message', 'Unknown error')}")
    except Exception as e:
        print(f"❌ Geocode error: {e}")
    _city_state_cache[key] = (None, None)
    return None, None

def get_coordinates_at_distance(miles_traveled: float, waypoints: List[Tuple[float, float]]) -> Tuple[float, float]:
    """Returns coordinates at a given distance along waypoints."""
    if len(waypoints) < 2:
        print("⚠️ Insufficient waypoints")
        return waypoints[0] if waypoints else (None, None)

    total_miles = 0
    for i in range(len(waypoints) - 1):
        step_distance = geodesic(waypoints[i], waypoints[i + 1]).miles
        total_miles += step_distance
        if total_miles >= miles_traveled:
            return waypoints[i + 1]
    return waypoints[-1]

def get_route_distance(start: Dict[str, str], finish: Dict[str, str]) -> Optional[Dict[str, any]]:
    """Calculates route distance and waypoints using Google Directions API."""
    params = {
        "origin": f"{start['city']}, {start['state']}",
        "destination": f"{finish['city']}, {finish['state']}",
        "key": GOOGLE_MAPS_API_KEY,
        "mode": "driving",
    }
    try:
        response = requests.get(DIRECTIONS_API_URL, params=params, timeout=5)
        data = response.json()
        if response.status_code != 200 or not data.get("routes"):
            print(f"⚠️ Directions API error: {data.get('error_message', 'No routes')}")
            return None

        leg = data["routes"][0]["legs"][0]
        total_distance = leg["distance"]["value"] * 0.000621371  # Meters to miles
        waypoints = polyline.decode(data["routes"][0]["overview_polyline"]["points"])
        print(f"✅ Route from {start['city']}, {start['state']} to {finish['city']}, {finish['state']}: {total_distance:.2f} miles")
        return {
            "total_distance_miles": round(total_distance, 2),
            "estimated_travel_time": leg["duration"]["text"],
            "waypoints": waypoints,
        }
    except Exception as e:
        print(f"❌ Route error: {e}")
        return None

def prefilter_gas_stations_along_route(waypoints: List[Tuple[float, float]], gas_stations: pd.DataFrame) -> pd.DataFrame:
    """Pre-filters gas stations near the route waypoints to reduce search space."""
    relevant_stations = []
    waypoint_coords = set(waypoints)  # Convert to set for O(1) lookup
    
    for _, station in gas_stations.iterrows():
        # If lat/lon are available, check proximity to waypoints
        if "latitude" in station and "longitude" in station and pd.notna(station["latitude"]) and pd.notna(station["longitude"]):
            station_coords = (station["latitude"], station["longitude"])
            min_distance = min(geodesic(station_coords, wp).miles for wp in waypoint_coords)
            if min_distance <= 100:  # Arbitrary threshold (miles) to include stations near route
                relevant_stations.append(station)
                continue
        
        # Fallback to city/state matching
        city, state = station["city"], station["state"]
        for lat, lon in waypoint_coords:
            wp_city, wp_state = get_city_state_from_coordinates(lat, lon)
            if wp_city == city and wp_state == state:
                relevant_stations.append(station)
                break

    filtered_df = pd.DataFrame(relevant_stations)
    print(f"✅ Pre-filtered {len(filtered_df)} stations along route (from {len(gas_stations)})")
    return filtered_df

def find_closest_gas_station_within_range(
    start_miles: float,
    max_miles: float,
    waypoints: List[Tuple[float, float]],
    gas_stations: pd.DataFrame,
    used_stations: set
) -> Optional[Tuple[pd.Series, float]]:
    """Finds the closest gas station within a given range from start_miles."""
    total_miles = 0
    for i in range(len(waypoints) - 1):
        step_distance = geodesic(waypoints[i], waypoints[i + 1]).miles
        total_miles += step_distance
        
        if total_miles < start_miles:
            continue
        if total_miles > max_miles:
            break

        lat, lon = waypoints[i]
        city, state = get_city_state_from_coordinates(lat, lon)
        if not city or not state:
            continue

        matches = gas_stations[
            (gas_stations["city"] == city.lower()) & 
            (gas_stations["state"] == state.upper())
        ]
        if matches.empty:
            continue

        station = matches.iloc[0]
        if station["truckstop name"] in used_stations:
            continue

        print(f"✅ Found station: {station['truckstop name']} at {total_miles:.2f} miles")
        return station, total_miles

    print(f"⚠️ No station found between {start_miles:.2f} and {max_miles:.2f} miles")
    return None, None

def find_gas_stations_on_route(total_distance: float, gas_stations: pd.DataFrame, waypoints: List[Tuple[float, float]]) -> List[Dict[str, any]]:
    """Dynamically finds gas stations ensuring no leg exceeds VEHICLE_RANGE_MILES."""
    # Pre-filter stations along the route
    filtered_stations = prefilter_gas_stations_along_route(waypoints, gas_stations)
    
    fuel_stops = []
    miles_traveled = 0
    used_stations = set()

    while miles_traveled < total_distance:
        max_miles = min(miles_traveled + VEHICLE_RANGE_MILES, total_distance)
        station, next_stop_miles = find_closest_gas_station_within_range(
            miles_traveled, max_miles, waypoints, filtered_stations, used_stations
        )

        if station is None:
            print(f"❌ No gas station within {VEHICLE_RANGE_MILES} miles from {miles_traveled}. Risk of running out of fuel!")
            if miles_traveled == 0:
                raise ValueError("No gas station found near starting point")
            break

        used_stations.add(station["truckstop name"])
        distance_traveled = next_stop_miles - miles_traveled
        fuel_needed = distance_traveled / MPG
        fuel_price = station.get("retail price", 3.50)
        cost = round(fuel_needed * fuel_price, 2)

        fuel_stops.append({
            "name": station["truckstop name"],
            "address": station.get("address", "N/A"),
            "city": station["city"].title(),
            "state": station["state"],
            "fuel_price_per_gallon": round(fuel_price, 2),
            "fuel_needed_gallons": round(fuel_needed, 2),
            "total_cost": cost,
            "miles_traveled": next_stop_miles,
        })
        print(f"✅ Added stop: {station['truckstop name']} at {next_stop_miles:.2f} miles")
        miles_traveled = next_stop_miles

    total_fuel = sum(stop["fuel_needed_gallons"] for stop in fuel_stops)
    expected_fuel = total_distance / MPG
    if abs(total_fuel - expected_fuel) > 0.1:
        print(f"⚠️ Warning: Total fuel ({total_fuel:.2f} gallons) does not match distance ({expected_fuel:.2f} gallons)")

    return fuel_stops

def calculate_total_fuel_cost(fuel_stops: List[Dict[str, any]]) -> float:
    """Calculates total fuel cost for the trip."""
    total = round(sum(stop["total_cost"] for stop in fuel_stops), 2)
    print(f"✅ Total fuel cost: ${total}")
    return total

def calculate_trip(start: str, finish: str) -> Dict[str, any]:
    """Main function to calculate trip details from start to finish."""
    try:
        start_city, start_state = (part.strip() for part in start.split(",", 1)) if "," in start else (None, None)
        finish_city, finish_state = (part.strip() for part in finish.split(",", 1)) if "," in finish else (None, None)
        
        if not all([start_city, start_state, finish_city, finish_state]):
            raise ValueError("Invalid start or finish format. Use 'City,State'.")

        start = {"city": start_city, "state": start_state}
        finish = {"city": finish_city, "state": finish_state}

        route = get_route_distance(start, finish)
        if not route:
            raise ValueError("Could not calculate route")

        gas_stations = load_gas_stations()
        fuel_stops = find_gas_stations_on_route(route["total_distance_miles"], gas_stations, route["waypoints"])
        total_cost = calculate_total_fuel_cost(fuel_stops)

        return {
            "total_distance_miles": route["total_distance_miles"],
            "estimated_travel_time": route["estimated_travel_time"],
            "fuel_stops": fuel_stops,
            "total_fuel_cost": total_cost
        }
    except Exception as e:
        print(f"❌ Trip calculation error: {e}")
        raise