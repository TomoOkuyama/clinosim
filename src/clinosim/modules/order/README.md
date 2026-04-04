# order

Order lifecycle management. Expands disease protocol definitions into concrete orders with timing.

## Public API

```python
from clinosim.modules.order.engine import (
    place_admission_orders,
    place_daily_lab_orders,
    calculate_lab_result_time,
)
```

### `place_admission_orders(protocol, patient_id, encounter_id, admission_time, country, rng) -> list[Order]`
Expands protocol's admission order set into concrete Order instances (labs, medications, supportive, imaging).

### `place_daily_lab_orders(protocol, patient_id, encounter_id, day, time, freq_multiplier, rng) -> list[Order]`
Places daily monitoring lab orders. Respects country-specific frequency multiplier (JP=1.3, US=0.8).

### `calculate_lab_result_time(order, rng) -> datetime`
Calculates when a lab result becomes available. STAT: ~45min, routine: ~2h. Night routine deferred to morning.

## Dependencies
- `clinosim.types.encounter` (Order, OrderType, OrderStatus, OrderResult)

## Testing
```bash
source .venv/bin/activate && python -m pytest tests/unit/test_order.py -v
```

## Implementation status
- [x] Admission order expansion from protocol YAML
- [x] Daily monitoring lab orders with frequency adjustment
- [x] Lab result timing model (STAT vs routine, night deferral)
- [ ] Medication order recurring schedule (q6h, BID, etc.)
- [ ] Imaging order timing
- [ ] Trigger order evaluation
- [ ] Equipment capacity constraints
