# Benchmark results (brick 9)

Model: qwen3.5-4b-16k, thinking on. A = Qwen alone (question only). B = Qwen + harness (run_agent).

| System | Accuracy per run | Mean ± sd | Min–max | Seconds per answer | Tokens per answer |
|---|---|---|---|---|---|
| A · Qwen alone | 8%, 17%, 25% | 17% ± 8% | 8%–25% | 210.4 ± 94.5 | 4785 ± 1972 |
| B · Qwen + harness | 100%, 92%, 100% | 97% ± 5% | 92%–100% | 57.1 ± 40.6 | 13822 ± 10255 |

| Task | Question | A | B |
|---|---|---|---|
| 1 | How many different routes (departure station -> arrival station) are in the TGV punctuality dataset? | 0/3 | 3/3 |
| 2 | Quel est le taux de retard à l'arrivée de Paris Lyon vers Marseille St Charles en 2024 ? | 0/3 | 3/3 |
| 3 | What share of TGV trains from Paris Montparnasse to Bordeaux St Jean arrived late in 2023? | 1/3 | 3/3 |
| 4 | Quel est le taux de retard à l'arrivée de Lyon Part Dieu à Marseille St Charles en juillet 2025 ? | 0/3 | 2/3 |
| 5 | What share of all TGV trains arrived late in 2024? | 0/3 | 3/3 |
| 6 | How many TGV trains were cancelled in 2023, all routes together? | 0/3 | 3/3 |
| 7 | Combien de TGV ont circulé de Paris Est à Strasbourg en 2022 ? | 0/3 | 3/3 |
| 8 | What was the cancellation rate of TGV trains from Paris Lyon to Nice Ville in 2024? | 0/3 | 3/3 |
| 9 | How many TGV trains were more than 60 minutes late in 2024, all routes together? | 0/3 | 3/3 |
| 10 | Quel est le taux de retard à l'arrivée des TGV de Paris Gare de Lyon à Marseille en 2023 ? | 0/3 | 3/3 |
| 11 | From how many minutes of delay is a TGV from Paris Nord to Lille counted as late? | 2/3 | 3/3 |
| 12 | Which full year between 2018 and 2025 had the highest share of TGV trains arriving late? | 3/3 | 3/3 |
