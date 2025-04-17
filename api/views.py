from django.http import JsonResponse
from .utils import calculate_trip

def calculate_trip_view(request):
    """Handles the /api/calculate_trip/ endpoint."""
    start = request.GET.get("start")
    finish = request.GET.get("finish")
    
    if not start or not finish:
        return JsonResponse({"error": "Missing 'start' or 'finish' parameter"}, status=400)
    
    try:
        result = calculate_trip(start, finish)
        return JsonResponse(result)
    except Exception as e:
        return JsonResponse({"error": str(e)}, status=400)