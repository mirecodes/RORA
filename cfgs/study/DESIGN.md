# User study design (P01–P15)

Session per participant: `scripts/run_tutorial.sh Pxx` (Skip ▸▸ at the top right drops a practice trial),
then `scripts/run_study.sh Pxx`. Files: `cfgs/study/Pxx/Pxx_tutorial.yml`, `cfgs/study/Pxx/Pxx.yml`.
Condition A = manual triad joints, B = suggested vectors.

## Objects

15 PartNet v0 objects (dispenser/spray excluded), placed on a ring of 15 positions so the
categories repeat with period 5 (`1 2 1 2 3`):

| pos | 0 | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 | 11 | 12 | 13 | 14 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| object | bucket | box | fan | faucet | lamp | globe | folding_chair | microwave | refrigerator | safe | trashcan | toaster | usb | toilet | stapler |
| cat | 1 | 2 | 1 | 2 | 3 | 1 | 2 | 1 | 2 | 3 | 1 | 2 | 1 | 2 | 3 |

## Algorithm (participant p = 0..14 is P{p+1}, positions mod 15)

1. **Objects:** A set = positions p, p+1; B set = positions p+5, p+6. Two neighbouring positions
   are always from different categories. Because the B set is shifted by one category period, both
   sets have the same category pair (9 participants get {1,2}, 3 get {2,3}, 3 get {1,3}).
2. **Condition order (Williams, n=2):** p even → A then B (8 participants), p odd → B then A (7).
3. **Object order within a set (Williams, n=2):** the A set runs forward (p, p+1) and the B set runs
   reversed (p+6, p+5).
4. **Tutorial:** in positions p+10 .. p+14 (one full category period, none of them used by p), take
   the first object of each of p's two categories (scanning backwards when p is odd). Order: lower
   category first, `obj1 A → obj1 B → obj2 A → obj2 B` (each object manual, then suggestion).

## Resulting balance

- 60 test trials: each object is tested 4 times, 2 × A and 2 × B, and is 2 × first and 2 × second
  within its set.
- Each object appears in set 1 twice, except bucket (3) and globe (1); exact 2/2 for every object is
  impossible with 8 vs 7 order groups.
- Tutorial objects never overlap the participant's 4 test objects; each object is used in 1–3 tutorials.

## Schedule

| P | order | set 1 | set 2 | tutorial |
|---|---|---|---|---|
| P01 | A→B | bucket, box | folding_chair, globe | trashcan, toaster |
| P02 | B→A | microwave, folding_chair | box, fan | bucket, toilet |
| P03 | A→B | fan, faucet | refrigerator, microwave | usb, toilet |
| P04 | B→A | safe, refrigerator | faucet, lamp | box, stapler |
| P05 | A→B | lamp, globe | trashcan, safe | bucket, stapler |
| P06 | B→A | toaster, trashcan | globe, folding_chair | fan, faucet |
| P07 | A→B | folding_chair, microwave | usb, toaster | fan, box |
| P08 | B→A | toilet, usb | microwave, refrigerator | globe, folding_chair |
| P09 | A→B | refrigerator, safe | stapler, toilet | faucet, lamp |
| P10 | B→A | bucket, stapler | safe, trashcan | microwave, lamp |
| P11 | A→B | trashcan, toaster | box, bucket | globe, folding_chair |
| P12 | B→A | fan, box | toaster, usb | trashcan, refrigerator |
| P13 | A→B | usb, toilet | faucet, fan | microwave, refrigerator |
| P14 | B→A | lamp, faucet | toilet, stapler | toaster, safe |
| P15 | A→B | stapler, bucket | globe, lamp | trashcan, safe |
