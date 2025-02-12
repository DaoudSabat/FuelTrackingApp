import pandas as pd
import requests
from django.conf import settings
from geopy.distance import geodesic
import os
import polyline
# Constants
VEHICLE_RANGE_MILES = 500  # Maximum miles per full tank
MPG = 10  # Miles per gallon
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CSV_FILE_PATH = os.path.join(BASE_DIR, "api", "fuel-prices-for-be-assessment.csv")

# Google Maps API
GOOGLE_MAPS_API_KEY = settings.GOOGLE_MAPS_API_KEY
DIRECTIONS_API_URL = "https://maps.googleapis.com/maps/api/directions/json"


def load_gas_stations():
    """
    Loads gas station data from CSV and returns a cleaned DataFrame.
    """
    try:
        df = pd.read_csv(CSV_FILE_PATH, delimiter=",")  # Adjust delimiter if necessary
        df.columns = [col.strip().lower() for col in df.columns]  # Normalize column names
        if "city" not in df.columns or "state" not in df.columns:
            raise KeyError("Missing required columns: 'City' or 'State'")
        df["city"] = df["city"].str.strip().str.lower()  # Normalize city names
        df["state"] = df["state"].str.strip().str.upper()

        print("✅ Gas stations loaded successfully!")
        print("🚀 Available cities:", df["city"].unique())  # Debugging: Show all cities

        return df
    except FileNotFoundError:
        raise FileNotFoundError(f"CSV file not found at {CSV_FILE_PATH}")
    except Exception as e:
        raise Exception(f"Error loading CSV file: {e}")

def get_available_locations():
    """
    Returns a list of unique cities from the CSV file to populate dropdown menus.
    """
    df = load_gas_stations()
    locations = df[["city", "state"]].drop_duplicates().to_dict(orient="records")
    return locations
def get_city_state_from_coordinates(lat, lon):
    """
    Converts latitude/longitude into a city and state using Google Maps API.
    """
    base_url = "https://maps.googleapis.com/maps/api/geocode/json"
    params = {
        "latlng": f"{lat},{lon}",
        "key": GOOGLE_MAPS_API_KEY
    }

    response = requests.get(base_url, params=params)

    # Debugging: Print full response
    print(f"🌍 Google API Response for ({lat}, {lon}): {response.text}")

    try:
        data = response.json()  # Attempt to parse JSON

        if "status" in data and data["status"] == "OK":
            city, state = None, None

            for component in data["results"][0]["address_components"]:
                if "locality" in component["types"]:
                    city = component["long_name"]
                if "administrative_area_level_1" in component["types"]:
                    state = component["short_name"]

            if city and state:
                print(f"✅ Matched waypoint to {city}, {state}")
                return city, state
        else:
            print(f"⚠️ Google API Error: {data.get('error_message', 'No data received')}")
    except Exception as e:
        print(f"❌ JSON Decode Error: {e}")

    return None, None


def get_coordinates_at_distance(miles_traveled, waypoints):
    """
    Returns the coordinates at a given distance along the route.
    Args:
        miles_traveled (float): Distance traveled so far in miles.
        waypoints (list): List of waypoints (latitude, longitude) along the route.
    Returns:
        tuple: Latitude and longitude of the current location.
    """
    if not waypoints or len(waypoints) < 2:
        print("⚠️ Not enough waypoints to determine coordinates.")
        return None, None

    total_miles = 0

    for i in range(len(waypoints) - 1):
        lat1, lon1 = waypoints[i]
        lat2, lon2 = waypoints[i + 1]

        # Approximate distance between waypoints
        step_distance = geodesic((lat1, lon1), (lat2, lon2)).miles
        total_miles += step_distance

        # If we reach the requested distance, return this waypoint
        if total_miles >= miles_traveled:
            return lat2, lon2  # Move to the next waypoint

    return waypoints[-1]         

def get_route_distance(start, finish):
    """
    Uses Google Directions API to calculate total distance between start and finish.
    """
    params = {
        "origin": f"{start['city']}, {start['state']}",
        "destination": f"{finish['city']}, {finish['state']}",
        "key": GOOGLE_MAPS_API_KEY,
        "mode": "driving",
    }

    response = requests.get(DIRECTIONS_API_URL, params=params)
    data = response.json()
    print("🚀 Full Google API Response:", data)  # Debugging output


    # ✅ Check if response contains routes
    if response.status_code != 200 or "routes" not in data or not data["routes"]:
        print(f"⚠️ Google API Error: {data.get('error_message', 'Unknown error')}")
        return None

    try:
        route = data["routes"][0]["legs"][0]  # First route leg

        total_distance = route["distance"]["value"] * 0.000621371  # Convert meters to miles
        total_time = route["duration"]["text"]  # Readable travel time

        # ✅ Safe check before decoding polyline
        if "overview_polyline" not in data["routes"][0]:
            print("⚠️ No polyline found in response.")
            return None
        
        polyline_data = data["routes"][0]["overview_polyline"]["points"]
        waypoints = polyline.decode(polyline_data)  # Converts encoded polyline to lat/lon list
        print(f"🚀 Extracted {len(waypoints)} waypoints: {waypoints[:5]} ...")

        return {
            "total_distance_miles": round(total_distance, 2),
            "estimated_travel_time": total_time,
            "waypoints": waypoints,  # List of lat/lon points
        }

    except KeyError as e:
        print(f"❌ KeyError: {e} - Missing key in Google response")
    except Exception as e:
        print(f"❌ Unexpected error: {e}")

    return None
def geocode_address(address, csv_file_path="fuel-prices-for-be-assessment.csv"):
    """
    Converts an address to latitude and longitude using Google Maps Geocoding API.
    Adds a nearby city/state if the address is a highway exit.
    If geocoding fails, tries to get coordinates from the city/state in the CSV.
    """
    GEOCODE_API_URL = "https://maps.googleapis.com/maps/api/geocode/json"

    # Check if address looks like a highway exit
    if "EXIT" in address or "I-" in address or "SR-" in address:
        print(f"⚠️ Address '{address}' looks like a highway exit. Adding fallback city/state.")
        address += ", USA"  # Adding ", USA" helps Google locate it.

    params = {
        "address": address,
        "key": settings.GOOGLE_MAPS_API_KEY
    }

    # Initial attempt to geocode the address
    response = requests.get(GEOCODE_API_URL, params=params)
    data = response.json()

    if response.status_code == 200 and data['results']:
        location = data['results'][0]['geometry']['location']
        print(f"Geocoded address '{address}' successfully: {location}")
        return location['lat'], location['lng']
    else:
        print(f"❌ Geocoding failed for: {address} | Error: {data.get('error_message', 'Unknown error')}")

        # If geocoding fails, fallback to the city/state from the CSV
        print(f"🔄 Trying fallback with city/state from the CSV.")
        return fallback_geocode_from_csv(address, csv_file_path)


def fallback_geocode_from_csv(address, csv_file_path):
    """
    Fallback function to geocode the address using city/state data from a CSV file.
    """
    df = pd.read_csv(csv_file_path)

    # Assuming the CSV has 'city' and 'state' columns
    df.columns = [col.strip().lower() for col in df.columns]  # Normalize column names

    # Extract city and state from the address to match the DataFrame
    city, state = address.split(",")[0], address.split(",")[1] if "," in address else (None, None)

    # Normalize city and state names
    city = city.strip().lower() if city else None
    state = state.strip().upper() if state else None

    if city and state:
        # Try to find matching city/state in CSV
        matching_row = df[(df['city'] == city) & (df['state'] == state)]

        if not matching_row.empty:
            city_lat, city_lon = matching_row.iloc[0]['latitude'], matching_row.iloc[0]['longitude']
            print(f"Found matching city/state in CSV. Coordinates: {city_lat}, {city_lon}")
            return city_lat, city_lon
        else:
            print(f"❌ No matching city/state found in the CSV for: {address}")
            return None, None  # Return None if no match found
    else:
        print(f"❌ Invalid city/state provided for fallback: {address}")
        return None, None
    
def find_nearest_gas_station_by_city(stop_city, stop_state, gas_stations, used_stations):
    """
    Finds a gas station in the same city/state as the waypoint.
    """
    stop_city = stop_city.strip().lower()  # Normalize case
    stop_state = stop_state.strip().upper()  # Ensure state is uppercase

    print(f"🚀 Searching for gas stations in {stop_city.title()}, {stop_state}...")

    # Normalize gas station city names
    gas_stations["city"] = gas_stations["city"].str.strip().str.lower()
    gas_stations["state"] = gas_stations["state"].str.strip().str.upper()

    # ✅ Attempt to find a station in the same city/state
    city_match = gas_stations[
        (gas_stations["city"] == stop_city) & (gas_stations["state"] == stop_state)
    ]

    if city_match.empty:
        print(f"❌ No gas stations found in {stop_city.title()}, {stop_state}.")
        return None

    # ✅ Fix: Select only the first row to prevent Series ambiguity
    nearest_station = city_match.iloc[0]

    # ✅ Ensure we get a single value, not a Series
    truckstop_name = nearest_station["truckstop name"]

    # Avoid duplicate stops
    if truckstop_name in used_stations:
        print(f"⚠️ Already used {truckstop_name}. Skipping.")
        return None
    
    used_stations.add(truckstop_name)
    return nearest_station

def find_nearest_waypoint(lat, lon, waypoints):
    """
    Finds the closest waypoint to the given latitude and longitude.
    """
    min_distance = float("inf")
    closest_waypoint = None

    for wp in waypoints:
        distance = geodesic((lat, lon), (wp[0], wp[1])).miles
        if distance < min_distance:
            min_distance = distance
            closest_waypoint = wp

    return closest_waypoint
def find_gas_stations_on_route(total_distance, gas_stations, waypoints):
    """
    Finds gas stations dynamically every 500 miles along the route.
    Uses waypoints to improve location accuracy.
    """
    fuel_stops = []
    miles_traveled = 0
    used_stations = set()

    while miles_traveled < total_distance:
        miles_traveled += VEHICLE_RANGE_MILES  # Move forward in 500-mile steps

        # ✅ Get the closest waypoint to our new location
        stop_lat, stop_lon = get_coordinates_at_distance(miles_traveled, waypoints)
        nearest_waypoint = find_nearest_waypoint(stop_lat, stop_lon, waypoints)

        print(f"📍 Moved to ({nearest_waypoint[0]}, {nearest_waypoint[1]}) at {miles_traveled} miles")

        # ✅ Get city/state for the waypoint location
        stop_city, stop_state = get_city_state_from_coordinates(nearest_waypoint[0], nearest_waypoint[1])

        if not stop_city or not stop_state:
            print(f"⚠️ Could not determine city/state for ({nearest_waypoint[0]}, {nearest_waypoint[1]}). Skipping.")
            continue  # Skip this stop if location is unknown

        # ✅ Find the nearest gas station **by city/state**
        nearest_station = find_nearest_gas_station_by_city(stop_city, stop_state, gas_stations, used_stations)

        if not nearest_station:
            print(f"❌ No gas station found in {stop_city.title()}, {stop_state}. Skipping.")
            continue

        used_stations.add(nearest_station["truckstop name"])  # Avoid duplicates

        # ✅ Calculate fuel usage and cost
        fuel_needed = VEHICLE_RANGE_MILES / MPG
        fuel_price = nearest_station.get("retail price", 3.50)  # Default price if missing
        cost = round(fuel_needed * fuel_price, 2)

        # ✅ Save the fuel stop
        fuel_stops.append({
            "name": nearest_station.get("truckstop name"),
            "address": nearest_station.get("address"),
            "city": nearest_station.get("city").title(),
            "state": nearest_station.get("state"),
            "fuel_price_per_gallon": round(fuel_price, 2),
            "fuel_needed_gallons": round(fuel_needed, 2),
            "total_cost": cost,
            "miles_traveled": min(miles_traveled, total_distance),
        })

        # ✅ Move forward along the route
        print(f"🚗 Continuing journey after refueling at {nearest_station['truckstop name']}.")

    return fuel_stops
def calculate_total_fuel_cost(fuel_stops):
    """
    Calculates total fuel cost for the entire trip.
    """
    return round(sum(stop["total_cost"] for stop in fuel_stops), 2)

