# SYNTHETIC DEMO CORPUS — 72 fictional journal entries (Sep 2025 -> Jun 2026).
#
# WHY THIS EXISTS: the real journal (data/) is private and gitignored, which
# would make the public repo un-runnable and CI un-testable. This corpus is the
# stand-in: fully fictional, committed to the repo, and built into its own
# ChromaDB index via the SAME pipeline (chunk.py -> database.py with
# JOURNAL_DEMO=1).
#
# WHY HAND-AUTHORED AND DETERMINISTIC (not LLM-generated): zero API quota, and —
# more importantly — every answer in evals/golden_set_demo.py is true BY
# CONSTRUCTION. The ground truths below are load-bearing; the demo golden set
# asserts them exactly.
#
# GROUND TRUTHS (change an entry, re-verify all of these):
#   - 72 entries total, 2025-09-02 .. 2026-06-05 (nothing after 06-05, so
#     "the last week" before EVAL_DATE 2026-06-30 is EMPTY -> honest decline)
#   - Sam: FIRST hangout 2025-09-14, LAST 2026-06-05, 9 hangouts total,
#     4 of them strictly after 2026-03-01 (03-14, 04-11, 05-16, 06-05)
#   - May 2026: exactly 18 entries; exactly 6 mention "gym"
#     (05-02, 05-06, 05-11, 05-15, 05-22, 05-29) -> 6/18 journaled days = ~33%
#   - "pottery": exactly 4 entries ever (02-07, 02-28, 03-21, 04-18)
#   - "Iceland": exactly 1 mention — a DOCUMENTARY on 2026-02-11, never a trip
#     (the honest-failure trap: "tell me about my trip to Iceland" must decline)
#   - Midterm arc: stress entries 04-19/20/21, physics midterm 04-22
#
# SUBSTRING LANDMINES (keyword matching is case-insensitive SUBSTRING —
# see chroma_search._keyword_match): the words "same"/"sesame"/"balsamic"
# contain "sam", so they must NEVER appear in any non-Sam entry. Run
# verify_ground_truths() (done automatically) after any content edit.

import json
import re
from pathlib import Path

# Always writes HERE, regardless of env vars — this script must never be able
# to touch the real data/ directory.
RAW_DIR = Path(__file__).parent / "data" / "raw"

# (date, title, content) — one entry per date, chronological.
ENTRIES = [
    # ---------------- SEPTEMBER 2025 ----------------
    ("2025-09-02", "First Day Back - 9/2/25",
     "First day of the fall semester. Physics 2 and Data Structures look like the heavy ones. "
     "Campus was packed and the bookstore line wrapped around the building. Made pasta for dinner and set up my planner."),
    ("2025-09-08", "Study Grind - 9/8/25",
     "Spent most of the day in the library working through the first problem set. "
     "It rained all afternoon. Called mom in the evening and she caught me up on everything back home."),
    ("2025-09-14", "Farmers Market with Sam - 9/14/25",
     "Met Sam for the first time today — friend of a friend from the climbing club group chat. "
     "We walked the farmers market downtown, split a box of peaches, and talked about music for two hours. "
     "Feels like the start of a real friendship."),
    ("2025-09-20", "Lazy Saturday - 9/20/25",
     "Did almost nothing today and honestly needed it. Watched half a season of a cooking show and made grilled cheese. "
     "Laundry finally got done at midnight."),
    ("2025-09-24", "Physics Panic - 9/24/25",
     "First physics quiz did not go great. I misread the units on the second problem and spiraled a bit. "
     "Going to start doing practice problems earlier instead of cramming the night before."),
    ("2025-09-29", "Coffee with Maya - 9/29/25",
     "Maya and I tried the new coffee place on 5th. Her latte art obsession continues. "
     "We planned a movie night for next month and complained about our schedules."),

    # ---------------- OCTOBER 2025 ----------------
    ("2025-10-04", "Long Run Morning - 10/4/25",
     "Ran four miles along the river trail before it got hot. Legs felt strong for the first time in a while. "
     "Spent the afternoon on the Data Structures project — linked lists are finally clicking."),
    ("2025-10-09", "Midweek Slump - 10/9/25",
     "One of those days where nothing big happened. Classes, leftovers, a nap that went too long. "
     "Started a new fantasy novel before bed."),
    ("2025-10-15", "Group Project Chaos - 10/15/25",
     "Our lab group met for three hours and produced roughly fifteen minutes of actual work. "
     "Diego kept us laughing at least. We finally divided up the sections near the end."),
    ("2025-10-20", "Rainy Reset - 10/20/25",
     "Rain all day. Cleaned the whole apartment, meal prepped for the week, and organized my notes. "
     "Feeling weirdly accomplished for a day I never left the building."),
    ("2025-10-25", "Corn Maze with Sam - 10/25/25",
     "Sam drove us out to the corn maze an hour outside the city. We got properly lost for forty minutes "
     "and blamed each other the entire time. Hot cider after. Great day."),
    ("2025-10-30", "Halloween Prep - 10/30/25",
     "Carved a pumpkin that was supposed to be a cat and came out looking like a confused owl. "
     "Maya is doing a group costume and roped me in."),

    # ---------------- NOVEMBER 2025 ----------------
    ("2025-11-03", "Crunch Week Begins - 11/3/25",
     "Two exams next week so the library is home now. Made flashcards for physics and re-did the practice midterm. "
     "Bribing myself with snacks is working so far."),
    ("2025-11-08", "Exams Done - 11/8/25",
     "Both exams done. Physics went better than expected, Data Structures was rough but fair. "
     "Celebrated with pizza and twelve hours of sleep."),
    ("2025-11-14", "Movie Night with Maya - 11/14/25",
     "Maya hosted movie night — we watched an old heist film and she called every plot twist ten minutes early. "
     "Diego brought popcorn he somehow burned in a microwave."),
    ("2025-11-19", "Quiet Wednesday - 11/19/25",
     "Slow day. Went to class, came home, cooked stir fry, read my book. "
     "Sometimes an unremarkable day is exactly right."),
    ("2025-11-23", "Early Thanksgiving - 11/23/25",
     "Friendsgiving at Diego's place. I brought mac and cheese and it disappeared first, which I am taking as a trophy. "
     "We went around saying what we were thankful for and it got surprisingly sincere."),
    ("2025-11-29", "Home for Break - 11/29/25",
     "Back home for the holiday weekend. Helped dad rake the yard and ate way too much leftover stuffing. "
     "It is nice to sleep in my old room again."),

    # ---------------- DECEMBER 2025 ----------------
    ("2025-12-02", "Finals Loading - 12/2/25",
     "Finals schedule posted. Made a study calendar and immediately felt both better and worse. "
     "The library got loud so I found a hidden corner on the fourth floor."),
    ("2025-12-07", "Study Marathon - 12/7/25",
     "Nine hours of studying with breaks timed by a tomato timer app. Physics formulas are starting to stick. "
     "Rewarded myself with dumplings from the place on the corner."),
    ("2025-12-13", "Ice Skating with Sam - 12/13/25",
     "Post-finals celebration: Sam and I went ice skating downtown. I fell twice, Sam fell four times, "
     "and we agreed the scoreboard favors me. Hot chocolate after, extra marshmallows."),
    ("2025-12-18", "Winter Break Begins - 12/18/25",
     "Grades are in and I survived. Packed up and took the train home for break. "
     "Mom made my favorite curry and I fell asleep on the couch by nine."),
    ("2025-12-24", "Christmas Eve - 12/24/25",
     "Wrapped presents terribly, as is tradition. Baked cookies with my sister and watched the claymation specials. "
     "Snow started falling right after dinner, which felt like a movie scene."),
    ("2025-12-30", "Year End Reflection - 12/30/25",
     "Spent the evening journaling about the year. Made three resolutions: exercise more consistently, "
     "read twelve books, and say yes to more spontaneous plans."),

    # ---------------- JANUARY 2026 ----------------
    ("2026-01-05", "Back to Campus - 1/5/26",
     "Train back to school. New semester, new notebook, delusional levels of optimism. "
     "Signed up for the campus gym membership to make the exercise resolution real."),
    ("2026-01-10", "Cold Snap - 1/10/26",
     "Eight degrees outside. Classes felt twice as long. Made a giant pot of chili that should last three days. "
     "Started book one of twelve for the year."),
    ("2026-01-16", "Routine Forming - 1/16/26",
     "Morning lecture, afternoon gym session, evening reading. If I can keep this rhythm the semester might actually be civilized. "
     "Legs sore in the good way."),
    ("2026-01-21", "Study Group Launch - 1/21/26",
     "Started a weekly study group for Thermodynamics with Diego and two people from lecture. "
     "We booked a library room through March. Feeling organized for once."),
    ("2026-01-24", "Ramen Crawl with Sam - 1/24/26",
     "Sam had the idea to try two ramen places in one night and rank them. The second place won on broth alone. "
     "We walked it off in the cold arguing about the rankings."),
    ("2026-01-29", "Small Wins - 1/29/26",
     "Aced the first thermo quiz. Treated myself to a fancy pastry and did absolutely no work after seven pm. Balance."),

    # ---------------- FEBRUARY 2026 ----------------
    ("2026-02-03", "Snow Day - 2/3/26",
     "Campus closed for snow. Built a lopsided snowman with the neighbors and drank an irresponsible amount of cocoa. "
     "Finished book two of the year."),
    ("2026-02-07", "First Pottery Class - 2/7/26",
     "Signed up for a pottery class on a whim and had the best time. My bowl collapsed twice before it held. "
     "There is something meditative about the wheel — you cannot think about anything else while using it."),
    ("2026-02-11", "Documentary Night - 2/11/26",
     "Maya came over and we watched a documentary about Iceland — the volcanoes, the hot springs, the black sand beaches. "
     "Added it to the someday-travel list. Someday."),
    ("2026-02-16", "Long Library Day - 2/16/26",
     "Thermo problem set ate the whole day. The study group session saved me on the last two problems. "
     "Note to self: start these earlier."),
    ("2026-02-21", "Trivia Night with Sam - 2/21/26",
     "Sam recruited me for pub trivia and we came in second place out of eleven teams. "
     "We lost on a geography question and Sam has not stopped talking about it."),
    ("2026-02-25", "Feeling the Grind - 2/25/26",
     "Midweek tiredness setting in. Skipped my workout, ordered takeout, watched comfort TV. "
     "Tomorrow I will be a functional person again. Tonight, noodles."),
    ("2026-02-28", "Pottery Progress - 2/28/26",
     "Second pottery class. My bowl survived the wheel this time and even looks intentional. "
     "The instructor said my centering has improved. Glazing happens next month."),

    # ---------------- MARCH 2026 ----------------
    ("2026-03-04", "Spring Teaser - 3/4/26",
     "First warm day of the year. Took my reading outside to the quad like everyone else on campus. "
     "Book three done — ahead of schedule."),
    ("2026-03-09", "Project Kickoff - 3/9/26",
     "The big Thermodynamics project got assigned: model a heat exchanger by end of April. "
     "Diego and I claimed the topic we wanted before anyone else could."),
    ("2026-03-14", "Hiking with Sam - 3/14/26",
     "Sam and I drove out to the state park and hiked the ridge loop — about seven miles. "
     "Perfect weather, ridiculous views, one very bold squirrel that tried to join lunch. Best day of the semester so far."),
    ("2026-03-21", "Pottery Glazing Day - 3/21/26",
     "Third pottery class: glazed the bowl a deep ocean blue. It goes in the kiln next session. "
     "I understand now why people get addicted to this hobby."),
    ("2026-03-26", "Spring Break Prep - 3/26/26",
     "Wrapped up assignments before break. Packed for the trip home and cleaned out the fridge of anything suspicious. "
     "Train tomorrow morning."),
    ("2026-03-30", "Break at Home - 3/30/26",
     "Slow week at home. Helped mom repaint the porch railing and beat my sister at cards three nights running. "
     "Exactly the recharge I needed."),

    # ---------------- APRIL 2026 ----------------
    ("2026-04-03", "Back in the Swing - 4/3/26",
     "Back on campus and straight into the heat exchanger project. Our first simulation run produced numbers "
     "that violate the laws of physics, which Diego found funnier than I did."),
    ("2026-04-08", "Gym Rhythm Restored - 4/8/26",
     "Got back into the gym routine after break — three sessions this week. "
     "Also fixed the simulation bug: a unit conversion, because it is always a unit conversion."),
    ("2026-04-13", "Sunday Reset - 4/13/26",
     "Groceries, laundry, meal prep, one long walk. Called grandma and she told the story about the runaway goat again. "
     "I would listen to it a hundred more times."),
    ("2026-04-18", "Pottery Finale - 4/18/26",
     "Last pottery class of the course. The kiln-fired bowl came out better than I had any right to expect — "
     "the blue glaze pooled darker at the bottom like a tide. It now holds my keys and my pride."),
    ("2026-04-19", "Pre-Midterm Nerves - 4/19/26",
     "The physics midterm is Wednesday and the practice exam humbled me tonight. "
     "Stressed about the rotational dynamics section. Made a plan: one topic per night, sleep before midnight."),
    ("2026-04-20", "Grinding Through - 4/20/26",
     "Stress level still high but the plan is working. Rotational dynamics finally cracked after two hours of problems. "
     "Went for a short run to burn off the nerves and it genuinely helped."),
    ("2026-04-21", "Night Before - 4/21/26",
     "Last review done. I know the material better than I feel like I do — writing that down so future me remembers "
     "the feeling is always worse than the reality. Early night."),
    ("2026-04-22", "Physics Midterm - 4/22/26",
     "Midterm day. All the practice paid off — the rotational dynamics problem I feared was the one I nailed. "
     "Walked out feeling steady. Celebrated with ramen and an early night. The stress of the last few days finally lifted."),

    # ---------------- MAY 2026 (exactly 18 entries, exactly 6 with "gym") ----------------
    ("2026-05-01", "May Day - 5/1/26",
     "Project crunch month begins. Mapped out every deadline between now and finals on a whiteboard. "
     "It looks scary but at least it all fits."),
    ("2026-05-02", "Gym Saturday - 5/2/26",
     "Morning gym session — new personal best on squats. Spent the afternoon on the project write-up. "
     "Balance achieved, briefly."),
    ("2026-05-03", "Sunday Slow - 5/3/26",
     "Recovery day. Farmers omelet, a long walk by the river, and two chapters of book five. "
     "Batteries recharging."),
    ("2026-05-05", "Deadline Dominoes - 5/5/26",
     "Turned in the thermo problem set and immediately started the next one. The assembly line of May. "
     "Diego and I booked extra library time for the project."),
    ("2026-05-06", "Gym Before Grind - 5/6/26",
     "Early gym workout to start the day right, then six hours of heat exchanger simulations. "
     "Our results finally match the reference data within two percent."),
    ("2026-05-08", "Small Celebration - 5/8/26",
     "Project simulation section officially done. Celebrated with tacos and a movie. "
     "The write-up is all that remains."),
    ("2026-05-10", "Mothers Day Call - 5/10/26",
     "Long call home for Mothers Day. Mom gave a full report on the porch railing holding up. "
     "Quiet study evening after."),
    ("2026-05-11", "Gym Reset - 5/11/26",
     "Legs day at the gym, then library. My study group is fraying at the edges as finals approach — "
     "everyone is tired. Two more weeks."),
    ("2026-05-13", "Rain and Review - 5/13/26",
     "Rainy day, perfect for flashcards. Re-derived every thermo formula from scratch to test myself. "
     "Only got stuck twice, which is progress."),
    ("2026-05-15", "Gym Therapy - 5/15/26",
     "Stress was building so I hit the gym and it worked like it always does. "
     "Evening spent polishing the project write-up intro."),
    ("2026-05-16", "Botanical Gardens with Sam - 5/16/26",
     "Sam dragged me to the botanical gardens as a study break and it was exactly what my brain needed. "
     "The rose section was peaking. We made a pact to do one non-study outing per week until finals end."),
    ("2026-05-18", "Project Submitted - 5/18/26",
     "Heat exchanger project SUBMITTED. Four hundred simulations, one beautiful report, zero remaining sanity. "
     "Diego and I high-fived like we had won a championship."),
    ("2026-05-20", "Evening Run - 5/20/26",
     "Finals stress is real now, so I have been leaning on the routines that work: an evening run to clear my head, "
     "then focused review blocks with real breaks. It kept the panic at arm's length today."),
    ("2026-05-22", "Gym Between Exams - 5/22/26",
     "First final done this morning — thermo, and it went well. Hit the gym in the afternoon to reset, "
     "then started reviewing for the next one."),
    ("2026-05-24", "Movie Break with Maya - 5/24/26",
     "Maya declared a mandatory movie night between finals and she was right, as usual. "
     "Two hours of not thinking about exams did more for me than two hours of studying would have."),
    ("2026-05-26", "Journaling the Nerves - 5/26/26",
     "One final left. Journaling before bed has become my pressure valve this month — "
     "writing the worry down seems to shrink it. Also meal prepped so future me eats real food this week."),
    ("2026-05-29", "Last Final + Gym - 5/29/26",
     "LAST FINAL DONE. Walked straight from the exam hall to the gym and lifted the stress away, "
     "then slept for eleven hours. Semester: survived."),
    ("2026-05-31", "May Wrap - 5/31/26",
     "Cleaned the apartment, returned my library books, and did a whole lot of nothing. "
     "Summer officially starts now. Book six finished at midnight — halfway to the reading goal."),

    # ---------------- JUNE 2026 (nothing after 06-05) ----------------
    ("2026-06-01", "Summer Mode - 6/1/26",
     "First real day of summer break. Slept in, made pancakes, started planning the internship search. "
     "The pace change feels illegal."),
    ("2026-06-03", "Walk and Talk - 6/3/26",
     "Long evening walk, then called Maya to debrief the semester. We rated it a solid seven out of ten. "
     "Started sketching a summer routine so the weeks do not evaporate."),
    ("2026-06-05", "Lake Day with Sam - 6/5/26",
     "Sam borrowed a cousin's kayaks and we spent the whole day at the lake. Paddled to the little island, "
     "ate sandwiches on the rocks, got mildly sunburned, regretted nothing. Perfect start to the summer."),
]

# ---------------- ground-truth verification (runs on every generation) ----------------

def verify_ground_truths():
    """Assert every fact the demo golden set depends on. Fails loudly on drift."""
    dates = [d for d, _, _ in ENTRIES]
    assert len(ENTRIES) == 72, f"expected 72 entries, got {len(ENTRIES)}"
    assert len(set(dates)) == 72, "duplicate dates"
    assert dates == sorted(dates), "entries out of order"
    assert max(dates) == "2026-06-05", "corpus must end 2026-06-05 (empty last week)"

    def full_text(entry):
        return (entry[1] + " " + entry[2]).lower()

    sam = [d for d, t, c in ENTRIES if "sam" in (t + " " + c).lower()]
    assert sam == ["2025-09-14", "2025-10-25", "2025-12-13", "2026-01-24",
                   "2026-02-21", "2026-03-14", "2026-05-16", "2026-06-05"], \
        f"'sam' substring appears in unexpected entries: {sam}"

    may = [e for e in ENTRIES if e[0].startswith("2026-05")]
    assert len(may) == 18, f"May 2026 must have exactly 18 entries, got {len(may)}"
    may_gym = [e[0] for e in may if "gym" in full_text(e)]
    assert may_gym == ["2026-05-02", "2026-05-06", "2026-05-11",
                       "2026-05-15", "2026-05-22", "2026-05-29"], \
        f"May 'gym' entries drifted: {may_gym}"

    pottery = [d for d, t, c in ENTRIES if "pottery" in (t + " " + c).lower()]
    assert pottery == ["2026-02-07", "2026-02-28", "2026-03-21", "2026-04-18"], \
        f"'pottery' entries drifted: {pottery}"

    iceland = [d for d, t, c in ENTRIES if "iceland" in (t + " " + c).lower()]
    assert iceland == ["2026-02-11"], f"'iceland' must appear exactly once: {iceland}"

    maya = [d for d, t, c in ENTRIES if "maya" in (t + " " + c).lower()]
    assert "2026-05-24" in maya and "2026-06-03" in maya, "recent Maya entries missing"

    print("Ground truths verified:")
    print(f"  72 entries, {dates[0]} .. {dates[-1]}")
    print(f"  Sam: first {sam[0]}, last {sam[-1]}, {len(sam)} hangouts, "
          f"{len([d for d in sam if d > '2026-03-01'])} after 2026-03-01")
    print(f"  May 2026: {len(may)} entries, {len(may_gym)} gym days")
    print(f"  pottery: {len(pottery)} entries | iceland mentions: {len(iceland)} (documentary only)")


def generate():
    verify_ground_truths()
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    # clear stale demo entries so removed/renamed ones don't linger
    for old in RAW_DIR.glob("demo-*.json"):
        old.unlink()

    for i, (date, title, content) in enumerate(ENTRIES, start=1):
        page_id = f"demo-{i:04d}"
        document = {
            "page_id": page_id,
            "title": title,
            "created_time": f"{date}T20:30:00.000Z",
            "properties": {},
            "content": content,
        }
        (RAW_DIR / f"{page_id}.json").write_text(
            json.dumps(document, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    print(f"\nWrote {len(ENTRIES)} demo entries to {RAW_DIR}")
    print("Next: JOURNAL_DEMO=1 python chunk.py && JOURNAL_DEMO=1 python database.py")


if __name__ == "__main__":
    generate()
