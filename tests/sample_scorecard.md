# Sample Scorecard (25 solved examples)

Requests scored: 25

| Field | Accuracy |
|---|---|
| affordability_status | 20/25 |
| recommended_payment_method | 21/25 |
| amount_safe_to_pay | 4/25 |
| payment_plan | 20/25 |
| earliest_date_for_full_payment | 18/25 |
| spending_changes_needed | 21/25 |

## Mismatch details

### request_02
- amount: ours=21412210.25 exp=17229139.2

### request_03
- amount: ours=1083930.6199999996 exp=873000

### request_04
- status: ours=affordable_now exp=affordable_later
- method: ours=full_payment exp=wait
- amount: ours=12693000.0 exp=8401800
- plan: ours=2024-06-04:12693000 exp=2024-06-15:12693000
- earliest: ours=2024-06-04 exp=2024-06-15

### request_05
- status: ours=affordable_now exp=not_affordable
- method: ours=full_payment exp=not_recommended
- amount: ours=15488.0 exp=737
- plan: ours=2025-11-06:15488 exp=none
- earliest: ours=2025-11-06 exp=

### request_06
- status: ours=affordable_now exp=affordable_with_plan
- amount: ours=620.4 exp=603.3
- earliest: ours=2026-01-03 exp=2026-01-15
- changes: ours=none exp=stop:event_476

### request_07
- amount: ours=92770.01500000001 exp=87170.56
- earliest: ours=2024-10-15 exp=2024-10-23

### request_08
- amount: ours=432.56999999999994 exp=284.57

### request_10
- amount: ours=102771.62428571424 exp=12700

### request_11
- status: ours=affordable_later exp=affordable_with_plan
- method: ours=wait exp=full_payment
- amount: ours=4492087.01000002 exp=12510645
- plan: ours=2025-07-24:13110000 exp=2025-05-03:13110000
- earliest: ours=2025-07-24 exp=2025-07-15
- changes: ours=none exp=reduce_to:event_989:665950

### request_13
- status: ours=affordable_with_plan exp=affordable_later
- method: ours=full_payment exp=wait
- amount: ours=851.0395238095248 exp=433.4
- plan: ours=2024-03-07:941.60 exp=2024-05-15:941.60
- earliest: ours= exp=2024-05-15
- changes: ours=stop:event_1090|stop:event_1091 exp=none

### request_14
- amount: ours=779.48 exp=597.74

### request_15
- amount: ours=230.13999999999987 exp=83.05

### request_17
- amount: ours=274600.0 exp=243849.58
- earliest: ours=2026-03-01 exp=2026-03-15

### request_18
- amount: ours=288.15285714285756 exp=462

### request_19
- amount: ours=37951.95999999999 exp=28820
- plan: ours=2024-09-04:37951.96|2024-09-15:1708.04 exp=2024-09-04:28820|2024-09-15:10840

### request_20
- amount: ours=2713.1699999999983 exp=5400

### request_21
- amount: ours=1570.0500000000002 exp=1543.35
- changes: ours=stop:event_1815 exp=stop:event_1815|reduce_to:event_1816:23.50

### request_22
- amount: ours=529.94 exp=475.46

### request_23
- amount: ours=10156.442857142858 exp=9152

### request_24
- amount: ours=20403.440000000002 exp=13420

### request_25
- amount: ours=4234206.469999999 exp=1425000

