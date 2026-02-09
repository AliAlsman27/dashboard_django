from django.shortcuts import render
from .firebase_client import read_device

def device_dashboard(request, device_id="ESP32_001"):
    data = read_device(device_id) or {}

    matrix_total = data.get("matrix_total") or []
    # Ensure length 64, then convert to rows of 8
    matrix_rows = [matrix_total[i:i+8] for i in range(0, min(len(matrix_total), 64), 8)]

    raw_basket = data.get("basket_size")
    basket_size_display = None
    if raw_basket is not None:
        if isinstance(raw_basket, str):
            basket_size_display = raw_basket
        elif isinstance(raw_basket, dict):
            x = raw_basket.get("x", raw_basket.get("X", 0))
            y = raw_basket.get("y", raw_basket.get("Y", 0))
            z = raw_basket.get("z", raw_basket.get("Z", 0))
            basket_size_display = f"{float(x):.2f} × {float(y):.2f} × {float(z):.2f}"
        elif isinstance(raw_basket, (list, tuple)) and len(raw_basket) >= 3:
            basket_size_display = f"{float(raw_basket[0]):.2f} × {float(raw_basket[1]):.2f} × {float(raw_basket[2]):.2f}"

    context = {
        "device_id": data.get("device_id", device_id),
        "battery": data.get("battery"),
        "total_level": data.get("total_level"),
        "timestamp": data.get("timestamp"),
        "matrix_rows": matrix_rows,
        "basket_size_display": basket_size_display,
        # Keep raw too (useful for your 3D JS)
        "matrix_total": matrix_total,
    }
    return render(request, "dashboard/device.html", context)
