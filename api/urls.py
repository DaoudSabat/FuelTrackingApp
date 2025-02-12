from django.urls import path
from .views import calculate_trip, get_available_start_finish_locations  # Ensure correct import

urlpatterns = [
    path("locations/", get_available_start_finish_locations, name="get_available_locations"),
    path("calculate_trip/", calculate_trip, name="calculate_trip"),  # Correct function name
]