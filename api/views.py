from rest_framework.response import Response
from geopy.distance import geodesic
import pandas as pd
from rest_framework.decorators import api_view
from .utils import (
    get_available_locations,
    get_route_distance,
    find_gas_stations_on_route,
    load_gas_stations,
    calculate_total_fuel_cost,
    get_coordinates_at_distance,
    get_city_state_from_coordinates,
    find_nearest_gas_station_by_city,
    find_nearest_waypoint,
)

VEHICLE_RANGE_MILES = 440  # Maximum miles per full tank
MPG = 10  # Miles per gallon

@api_view(["GET"])
def get_available_start_finish_locations(request):
    """
    API endpoint that returns available locations from the CSV file.
    """
    locations = get_available_locations()
    return Response({"locations": locations})

@api_view(["GET"])
def calculate_trip(request):
    """
    API endpoint to calculate trip distance, fuel stops, and total fuel cost.
    Example usage:
    GET /api/calculate_trip/?start=Shorter,AL&finish=Montrose,CO
    """
    start_input = request.GET.get("start")
    finish_input = request.GET.get("finish")

    if not start_input or not finish_input:
        return Response({"error": "Both 'start' and 'finish' parameters are required."}, status=400)

    try:
        gas_stations = load_gas_stations()  # Load fuel station data

        # Extract and normalize user input
        start_city, start_state = map(str.strip, start_input.split(","))
        finish_city, finish_state = map(str.strip, finish_input.split(","))
        start_city, finish_city = start_city.lower(), finish_city.lower()
        start_state, finish_state = start_state.upper(), finish_state.upper()

        # Find the matching locations in the CSV
        start = gas_stations[(gas_stations["city"] == start_city) & (gas_stations["state"] == start_state)]
        finish = gas_stations[(gas_stations["city"] == finish_city) & (gas_stations["state"] == finish_state)]

        # Check if the start and finish locations exist
        if start.empty or finish.empty:
            return Response({
                "error": "Invalid start or finish location. Please check city names.",
                "available_cities": gas_stations["city"].unique().tolist()
            }, status=400)

        # Convert matched rows to dictionaries
        start, finish = start.iloc[0].to_dict(), finish.iloc[0].to_dict()

        # Get route details (total distance, estimated travel time, waypoints)
        route_details = get_route_distance(start, finish)
        if not route_details:
            return Response({"error": "Could not retrieve route from Google API."}, status=400)

        total_distance = route_details["total_distance_miles"]

        # Find fuel stops along the route every 500 miles
        fuel_stops = find_gas_stations_on_route(total_distance, gas_stations, route_details["waypoints"])

        # Calculate total fuel cost
        total_fuel_cost = calculate_total_fuel_cost(fuel_stops)

        return Response({
            "start": {"city": start["city"], "state": start["state"]},
            "finish": {"city": finish["city"], "state": finish["state"]},
            "total_distance_miles": total_distance,
            "estimated_travel_time": route_details["estimated_travel_time"],
            "fuel_stops": fuel_stops,
            "total_fuel_cost": total_fuel_cost
        })

    except Exception as e:
        return Response({"error": f"An unexpected error occurred: {str(e)}"}, status=500)


def find_gas_stations_on_route(total_distance, gas_stations, waypoints):
    """
    Finds gas stations dynamically every 500 miles along the route.
    Uses waypoints to improve location accuracy.
    """
    fuel_stops = []
    miles_traveled = 0
    used_stations = set()
    last_lat, last_lon = waypoints[0]  # Start at the first waypoint

    while miles_traveled <= total_distance:
        miles_traveled += VEHICLE_RANGE_MILES  # Move 500 miles forward

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

        if nearest_station is None:  # ✅ Correct way to check
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

        # ✅ **Move to the next segment of the journey**
        print(f"🚗 Continuing journey after refueling at {nearest_station['truckstop name']}.")

    return fuel_stops



