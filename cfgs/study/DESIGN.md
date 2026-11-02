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

1. **Objects:** A set = positions p, p+1, p+2; B set = positions p+5, p+6, p+7.
   Because the B set is shifted by one category period, both sets have the same category mix
   (9 participants get {1,2,3}, 3 get {1,1,2}, 3 get {1,2,2}).
2. **Condition order (Williams, n=2):** p even → A then B (8 participants), p odd → B then A (7).
3. **Object order within a set (Williams, n=3 = two mirrored 3×3 Latin squares).** A set uses row
   p mod 3 of square 1, B set uses the matching row of square 2:

   | p mod 3 | A set (square 1) | B set (square 2) |
   |---|---|---|
   | 0 | slots 0,1,2 | slots 0,2,1 |
   | 1 | slots 1,2,0 | slots 1,0,2 |
   | 2 | slots 2,0,1 | slots 2,1,0 |

   Each of the 6 Williams sequences is used 5 times.
4. **Tutorial:** in positions p+10 .. p+14 (one full category period, all of them unused by p), take
   the first cat-1, cat-2 and cat-3 object (scanning backwards when p is odd). Order for every
   participant: cat-1 A, cat-1 B, cat-2 A, cat-2 B, cat-3 A, cat-3 B (each object manual, then suggestion).

## Resulting balance

- Each object is tested 6 times: 3 × A, 3 × B; 2 × each position (1st/2nd/3rd) within a set.
- Each object appears in set 1 two to four times (exact 3/3 is impossible with 8 vs 7 order groups).
- Tutorial objects never overlap the participant's 6 test objects; tutorial use is 2–3 per cat-1/2 object
  and 5 per cat-3 object.

## Schedule

| P | order | set 1 | set 2 | tutorial |
|---|---|---|---|---|
| P01 | A→B | bucket, box, fan | globe, microwave, folding_chair | trashcan, toaster, stapler |
| P02 | B→A | microwave, folding_chair, refrigerator | fan, faucet, box | bucket, toilet, stapler |
| P03 | A→B | lamp, fan, faucet | safe, refrigerator, microwave | usb, toilet, stapler |
| P04 | B→A | refrigerator, trashcan, safe | faucet, lamp, globe | fan, box, stapler |
| P05 | A→B | globe, folding_chair, lamp | trashcan, safe, toaster | bucket, box, stapler |
| P06 | B→A | usb, toaster, trashcan | microwave, globe, folding_chair | fan, faucet, lamp |
| P07 | A→B | folding_chair, microwave, refrigerator | toaster, toilet, usb | fan, box, lamp |
| P08 | B→A | toilet, usb, stapler | refrigerator, safe, microwave | globe, folding_chair, lamp |
| P09 | A→B | trashcan, refrigerator, safe | bucket, stapler, toilet | globe, faucet, lamp |
| P10 | B→A | stapler, box, bucket | safe, trashcan, toaster | microwave, refrigerator, lamp |
| P11 | A→B | toaster, usb, trashcan | box, bucket, fan | globe, folding_chair, safe |
| P12 | B→A | faucet, fan, box | toilet, toaster, usb | trashcan, refrigerator, safe |
| P13 | A→B | usb, toilet, stapler | fan, lamp, faucet | microwave, refrigerator, safe |
| P14 | B→A | lamp, faucet, globe | stapler, bucket, toilet | usb, toaster, safe |
| P15 | A→B | box, stapler, bucket | folding_chair, globe, lamp | trashcan, toaster, safe |
