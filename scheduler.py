from constraint import Problem
from request_handler import handle
import sys
import time as lib_time

# 1. Define problem
problem = Problem()

# 2. Get requests and resources
requests = handle()
all_rooms = ["Room1", "Room2"]

# 3. Add variables with prioritized time slots
for req in requests:
    valid_slots = []
    days = req["days"]
    
    # Sort time slots by preference 
    for day in days:
        for time in sorted(req["time_slots"], key=lambda x: ["9-11", "11-1", "1-3", "3-5", "5-7", "7-9"].index(x)):
            for room in all_rooms:
                valid_slots.append((day, time, room))
    
    problem.addVariable(req["name"], valid_slots)

# 4. Add constraints
def no_overlap(a, b):
    return a[2] != b[2] or a[0] != b[0] or a[1] != b[1]

for req1 in requests:
    for req2 in requests:
        if req1["name"] != req2["name"]:
            problem.addConstraint(no_overlap, [req1["name"], req2["name"]])

# 5. Optimization with flexible stopping
def evaluate_solution(solution):
    return sum(["9-11", "11-1", "1-3", "3-5", "5-7", "7-9"].index(slot[1]) 
               for req in requests 
               for slot in [solution[req["name"]]])

best_solution = None
best_score = sys.maxsize
start_time = lib_time.time()
max_time = 120  # Maximum search time in seconds
solutions_checked = 0

print("Searching for optimal schedule...")
for solution in problem.getSolutionIter():
    solutions_checked += 1
    current_score = evaluate_solution(solution)
    
    if current_score < best_score:
        best_solution = solution
        best_score = current_score
        print(f"New best: {best_score} (after {solutions_checked} solutions)")
    
    # Stop if we've taken too long
    if lib_time.time() - start_time > max_time:
        print(f"Time limit reached after {solutions_checked} solutions")
        break

    # Optional: Stop if we haven't improved in a while
    if solutions_checked % 100 == 0 and best_score < sys.maxsize:
        print(f"Still searching... Best so far: {best_score}")

if best_solution:
    print("\nBest Schedule Found:")
    for req in requests:
        day, time, room = best_solution[req["name"]]
        print(f"{req['name']:10} | {day:3} {time:5} | {room}")
    print(f"\nTotal 'earliness' score: {best_score}")
else:
    print("No valid schedule found")