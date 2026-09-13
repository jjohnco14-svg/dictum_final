"""Orchestration layer: argument parsing and CLI glue only. All pricing
logic lives in pricing_kernel.dict -- this file must never reimplement
it, only call it."""
import sys
sys.path.insert(0, ".")
from pricing_kernel_binding import calculate_tariff, is_valid_rate


def main():
    if not is_valid_rate(rate_class=2):
        print("invalid rate class")
        return 1
    result = calculate_tariff(weight_kg=10.0, distance_km=100.0, rate_class=2)
    print(f"tariff: {result}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
