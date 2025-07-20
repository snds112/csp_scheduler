from constraint import Problem, AllDifferentConstraint
from datetime import datetime, timedelta

class Scheduler:
    def __init__(self, reservations_data, places_config):
        self.reservations_data = reservations_data
        self.places_config = places_config
        self.problem = Problem()

        # Helper to store scheduled assignments (includes auto-approved and CSP-solved)
        self.scheduled_assignments = {}

        # Store original reservation details keyed by ID for easy lookup
        self._reservations_by_id = {res['id']: res for res in reservations_data}

    def _parse_time_slot(self, day_str, time_str):
        """Converts day and time strings to a datetime object for easier comparison."""
        return datetime.strptime(f"{day_str} {time_str}", "%Y-%m-%d %H:%M")

    def _do_times_overlap(self, start1, end1, start2, end2):
        """Checks if two time periods overlap."""
        return max(start1, start2) < min(end1, end2)

    def create_scheduling_problem(self):
        # Define all available places
        coworking_pc_desks = list(range(1, 25))
        lower_floor_places = [25] # Represents the group of 20 spots
        room_1_id = 101
        room_2_id = 102
        room_3_id = 103

        all_available_places = (
            coworking_pc_desks +
            lower_floor_places +
            [room_1_id, room_2_id, room_3_id]
        )

        pending_reservation_ids = []

        for reservation in self.reservations_data:
            res_id = reservation['id']
            # user_id = reservation['user_id'] # Not directly used in CSP for now, but for user attributes
            requested_place_id = reservation['place_id'] # This is their preference/request 
            formation_id = reservation['formation_id']
            day = reservation['day']
            start_time_str = reservation['start_time']
            end_time_str = reservation['end_time']
            request_status = reservation['request_status']

            start_dt = self._parse_time_slot(day, start_time_str)
            end_dt = self._parse_time_slot(day, end_time_str)

            # Auto-approve accepted reservations and formation reservations
            if request_status == 'accepted' or formation_id:
                self.scheduled_assignments[res_id] = {
                    'place_id': requested_place_id,
                    'start_time': start_dt,
                    'end_time': end_dt,
                    'status': 'scheduled'
                }
                continue # Skip adding this to CSP as it's fixed

            # For pending reservations, define CSP variables
            # The variable is the `place_id` that this reservation will be assigned to.
            # Its domain is the set of all possible places.
            self.problem.addVariable(f'res_{res_id}_place', all_available_places)
            pending_reservation_ids.append(res_id)

            # Constraint: A pending reservation cannot conflict with an already scheduled (fixed) reservation
            def create_fixed_conflict_constraint(current_res_id, fixed_res_details):
                current_start = self._reservations_by_id[current_res_id]['start_time']
                current_end = self._reservations_by_id[current_res_id]['end_time']
                current_day = self._reservations_by_id[current_res_id]['day']

                current_start_dt = self._parse_time_slot(current_day, current_start)
                current_end_dt = self._parse_time_slot(current_day, current_end)

                fixed_place_id = fixed_res_details['place_id']
                fixed_start_dt = fixed_res_details['start_time']
                fixed_end_dt = fixed_res_details['end_time']

                return lambda assigned_place: \
                    not (assigned_place == fixed_place_id and
                         self._do_times_overlap(current_start_dt, current_end_dt, fixed_start_dt, fixed_end_dt))

            for fixed_res_id, fixed_details in self.scheduled_assignments.items():
                self.problem.addConstraint(
                    create_fixed_conflict_constraint(res_id, fixed_details),
                    (f'res_{res_id}_place',)
                )


        # Constraint: No two *pending* reservations can occupy the same place at the same time.
        # This requires checking all pairs of pending reservations.
        for i, res_id1 in enumerate(pending_reservation_ids):
            for res_id2 in pending_reservation_ids[i+1:]:
                res1_start_dt = self._parse_time_slot(self._reservations_by_id[res_id1]['day'], self._reservations_by_id[res_id1]['start_time'])
                res1_end_dt = self._parse_time_slot(self._reservations_by_id[res_id1]['day'], self._reservations_by_id[res_id1]['end_time'])

                res2_start_dt = self._parse_time_slot(self._reservations_by_id[res_id2]['day'], self._reservations_by_id[res_id2]['start_time'])
                res2_end_dt = self._parse_time_slot(self._reservations_by_id[res_id2]['day'], self._reservations_by_id[res_id2]['end_time'])

                # Constraint: If assigned to the same place, their times must not overlap
                self.problem.addConstraint(
                    lambda place1, place2:
                        not (place1 == place2 and self._do_times_overlap(res1_start_dt, res1_end_dt, res2_start_dt, res2_end_dt)),
                    (f'res_{res_id1}_place', f'res_{res_id2}_place')
                )

        # Constraint: Handicapped people get assigned downstairs for lack of elevator 
        # This requires user data (e.g., a 'is_handicapped' flag).
        # Assuming you have user data, this would look like:
        # for reservation in self.reservations_data:
        #     if reservation['request_status'] == 'pending' and self._get_user_is_handicapped(reservation['user_id']):
        #         self.problem.addConstraint(lambda place: place == lower_floor_places[0], (f'res_{reservation["id"]}_place',))

        # Constraint: "add 20 people lower floor without pc in case 24 desks are full send people downstairs first then to meeting rooms if empty" 
        # This is a preference/optimization, not a hard CSP constraint. CSP finds *a* solution.
        # To implement this, you could:
        # 1. Prioritization through domain ordering (if the library supports it).
        # 2. Add soft constraints (if using a more advanced solver).
        # 3. Try to solve with only PC desks as domain for certain requests, then expand if no solution.
        # 4. Filter or order the solutions found by the CSP solver.
        # For this basic CSP, it will find any valid place.


        return self.problem

    def solve(self):
        print("Finding solutions for pending reservations...")
        solutions = self.problem.getSolutions()
        print(f"Found {len(solutions)} solutions.")

        if solutions:
            # We take the first solution found. In a real system, you might rank them.
            first_solution = solutions[0]
            for var_name, assigned_place_id in first_solution.items():
                res_id = int(var_name.split('_')[1])
                original_res = self._reservations_by_id[res_id]
                self.scheduled_assignments[res_id] = {
                    'place_id': assigned_place_id,
                    'start_time': self._parse_time_slot(original_res['day'], original_res['start_time']),
                    'end_time': self._parse_time_slot(original_res['day'], original_res['end_time']),
                    'status': 'scheduled'
                }
            return self.scheduled_assignments
        else:
            return None

# --- Dummy Data (from your CSV example) ---
dummy_reservations_data = [
    {'id': 1, 'user_id': 101, 'place_id': 5, 'formation_id': None, 'day': '2025-08-01', 'start_time': '09:00', 'end_time': '12:00', 'request_status': 'accepted'},
    {'id': 2, 'user_id': 102, 'place_id': 25, 'formation_id': None, 'day': '2025-08-01', 'start_time': '10:00', 'end_time': '13:00', 'request_status': 'pending'},
    {'id': 3, 'user_id': 103, 'place_id': 101, 'formation_id': 'F001', 'day': '2025-08-02', 'start_time': '14:00', 'end_time': '17:00', 'request_status': 'accepted'},
    {'id': 4, 'user_id': 104, 'place_id': 12, 'formation_id': None, 'day': '2025-08-02', 'start_time': '11:00', 'end_time': '16:00', 'request_status': 'pending'},
    {'id': 5, 'user_id': 105, 'place_id': 2, 'formation_id': None, 'day': '2025-08-03', 'start_time': '08:30', 'end_time': '10:30', 'request_status': 'accepted'},
    {'id': 6, 'user_id': 106, 'place_id': 103, 'formation_id': 'F002', 'day': '2025-08-04', 'start_time': '09:00', 'end_time': '17:00', 'request_status': 'accepted'},
    {'id': 7, 'user_id': 107, 'place_id': 25, 'formation_id': None, 'day': '2025-08-05', 'start_time': '13:00', 'end_time': '16:00', 'request_status': 'pending'},
    {'id': 8, 'user_id': 108, 'place_id': 15, 'formation_id': None, 'day': '2025-08-05', 'start_time': '09:00', 'end_time': '12:00', 'request_status': 'accepted'},
    {'id': 9, 'user_id': 109, 'place_id': 102, 'formation_id': None, 'day': '2025-08-06', 'start_time': '10:00', 'end_time': '12:00', 'request_status': 'rejected'},
    {'id': 10, 'user_id': 110, 'place_id': 7, 'formation_id': None, 'day': '2025-08-06', 'start_time': '14:00', 'end_time': '17:00', 'request_status': 'accepted'},
]

places_config = {
    'coworking_pc_desks': list(range(1, 25)),
    'lower_floor_no_pc': [25], # Represents the area
    'room_1': {'id': 101, 'capacity': 10},
    'room_2': {'id': 102, 'capacity': 10},
    'room_3': {'id': 103, 'capacity': 60},
}


if __name__ == "__main__":
    scheduler = Scheduler(dummy_reservations_data, places_config)
    scheduler.create_scheduling_problem()
    solution = scheduler.solve()

    if solution:
        print("\n--- Scheduled Reservations ---")
        for res_id, details in solution.items():
            original_res = scheduler._reservations_by_id[res_id]
            status = details.get('status', 'pending_scheduled') # 'pending_scheduled' if solved by CSP
            print(f"Reservation ID: {res_id}, User: {original_res['user_id']}, "
                  f"Assigned Place: {details['place_id']}, "
                  f"Original Requested Place: {original_res['place_id']}, " # Show original request
                  f"Start: {details['start_time'].strftime('%Y-%m-%d %H:%M')}, "
                  f"End: {details['end_time'].strftime('%H:%M')}, Status: {status}")
    else:
        print("No solution found that satisfies all constraints for pending reservations.")